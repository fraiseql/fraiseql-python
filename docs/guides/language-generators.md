<!-- Skip to main content -->
---

title: FraiseQL Language Generators
description: - GraphQL fundamentals (types, fields, queries, mutations, resolvers)
keywords: ["debugging", "implementation", "best-practices", "deployment", "tutorial"]
tags: ["documentation", "reference"]
---

# FraiseQL Language Generators

**Status:** ✅ Production Ready
**Audience:** Developers
**Reading Time:** 10-15 minutes
**Last Updated:** 2026-02-05

## Prerequisites

**Required Knowledge:**

- GraphQL fundamentals (types, fields, queries, mutations, resolvers)
- At least one programming language (Python, TypeScript, Java, or Go)
- Decorator/annotation syntax in your target language
- JSON schema structure and validation
- Type systems and generic types
- CLI tool usage and file I/O operations

**Required Software:**

- FraiseQL v2.0.0-alpha.1 or later
- Your chosen language runtime:
  - Python 3.10+ (for Python generator)
  - Node.js 18+ (for TypeScript generator)
  - Java 11+ with Maven (for Java generator)
  - Go 1.21+ (for Go generator)
- A code editor or IDE for your chosen language
- Git for version control
- Bash or equivalent shell

**Required Infrastructure:**

- FraiseQL CLI tooling (FraiseQL compile command)
- PostgreSQL 14+ database (for compilation validation)
- File system with write permissions for schema.json output
- Network connectivity for downloading language SDKs

**Optional but Recommended:**

- IDE extensions for your language (IntelliSense, syntax highlighting)
- Language package managers (pip, npm, Maven, go modules)
- Type checkers (mypy for Python, tsc for TypeScript, etc.)
- Code formatters for consistent style
- Schema visualization tools

**Time Estimate:** 20-40 minutes to create first schema, 1-2 hours to understand all language features

## Overview

FraiseQL v2 supports schema authoring in **5 programming languages**, all producing compatible JSON schemas that compile to the same optimized execution engine. This document describes each language generator, their features, and how to use them.

## Architecture

```text
<!-- Code example in TEXT -->
┌─────────────────────────────────────────────────────────────┐
│                  Language Generators                         │
├──────────────────┬──────────────────┬──────────────────┬────┤
│  Python          │  TypeScript      │  Java            │ Go │
│  (decorators)    │  (decorators)    │  (annotations)   │    │
└────────┬─────────┴────────┬─────────┴────────┬────────┴─┬──┘
         │                  │                  │          │
         └──────────────────┼──────────────────┼──────────┘
                            │
                      ┌─────▼──────┐
                      │ schema.json │ ← All produce this format
                      └─────┬──────┘
                            │
                      ┌─────▼──────────────┐
                      │ FraiseQL-cli       │
                      │ (compilation)      │
                      └─────┬──────────────┘
                            │
                      ┌─────▼──────────────────┐
                      │ schema.compiled.json   │
                      │ (optimized execution)  │
                      └────────────────────────┘
```text
<!-- Code example in TEXT -->

## Status Summary

| Language | Version | Status | Tests | Features |
|----------|---------|--------|-------|----------|
| Python | 2.0.0-a1 | ✅ Ready | 34/34 ✓ | Full support |
| TypeScript | 2.0.0-a1 | ✅ Ready | 10/10 ✓ | Full support |
| Go | 2.0.0-a1 | ✅ Ready | 45+ ✓ | Full support |
| Java | 2.0.0-a1 | ✅ Ready | 6 tests ✓ | Full support |
| PHP | 2.0.0-a1 | ✅ Ready | 15+ ✓ | Full support |

## Python Generator

### Installation

```bash
<!-- Code example in BASH -->
cd FraiseQL-python
pip install -e .
# or with uv:
uv sync
```text
<!-- Code example in TEXT -->

### Basic Usage

```python
<!-- Code example in Python -->
from FraiseQL import (
    type as fraiseql_type,
    query as fraiseql_query,
    mutation as fraiseql_mutation,
    schema as fraiseql_schema,
)

# Define types
@fraiseql_type
class User:
    id: UUID  # UUID v4 for GraphQL ID
    name: str
    email: str | None
    createdAt: str
    isActive: bool

@fraiseql_type
class Post:
    id: UUID  # UUID v4 for GraphQL ID
    title: str
    content: str
    authorId: int
    published: bool

# Define queries
@fraiseql_query(sql_source="v_users")
def users(limit: int = 10, offset: int = 0) -> list[User]:
    """Get all users."""
    pass

@fraiseql_query(sql_source="v_posts")
def posts(
    authorId: int | None = None,
    published: bool | None = None,
    limit: int = 10,
    offset: int = 0
) -> list[Post]:
    """Get posts with filtering."""
    pass

# Define mutations
@fraiseql_mutation(sql_source="fn_create_user")
def createUser(name: str, email: str) -> User:
    """Create a new user."""
    pass

# Export schema
fraiseql_schema.export_schema("schema.json")
```text
<!-- Code example in TEXT -->

### Analytics Support

```python
<!-- Code example in Python -->
from FraiseQL import fact_table, aggregate_query

@fact_table(
    table_name="tf_sales",
    measures=["revenue", "quantity", "cost"],
    dimension_paths=[
        {
            "name": "category",
            "json_path": "dimensions->>'category'",
            "data_type": "text"
        }
    ]
)
class SalesFactTable:
    revenue: float
    quantity: int
    cost: float

@aggregate_query(fact_table="tf_sales")
def salesByCategory(category: str) -> dict:
    """Sales aggregated by category."""
    pass
```text
<!-- Code example in TEXT -->

### Features

- ✅ Modern Python 3.10+ type hints
- ✅ Decorator-based schema definition
- ✅ Full analytics support (fact tables, measures)
- ✅ GraphQL type mapping
- ✅ JSON schema export
- ✅ CLI compilation support

### Testing

```bash
<!-- Code example in BASH -->
cd FraiseQL-python
python -m pytest tests/ -v

# E2E test
python -m pytest tests/e2e/python_e2e_test.py -v
```text
<!-- Code example in TEXT -->

## TypeScript Generator

### Installation

```bash
<!-- Code example in BASH -->
cd FraiseQL-typescript
npm install
# or
npm ci
```text
<!-- Code example in TEXT -->

### Basic Usage

```typescript
<!-- Code example in TypeScript -->
import { Type, Query, Mutation, SchemaRegistry, ExportSchema } from "./src/decorators";

// Define types
@Type()
class User {
  id!: number;
  name!: string;
  email?: string;
  createdAt!: string;
  isActive!: boolean;
}

@Type()
class Post {
  id!: number;
  title!: string;
  content!: string;
  authorId!: number;
  published!: boolean;
}

// Define queries
@Query(sql_source = "v_users")
users(limit?: number, offset?: number): User[] {
  return [];
}

@Query(sql_source = "v_posts")
posts(
  authorId?: number,
  published?: boolean,
  limit?: number,
  offset?: number
): Post[] {
  return [];
}

// Define mutations
@Mutation(sql_source = "fn_create_user")
createUser(name: string, email: string): User {
  return new User();
}

// Export schema
ExportSchema("schema.json");
```text
<!-- Code example in TEXT -->

### Analytics Support

```typescript
<!-- Code example in TypeScript -->
import { FactTable, AggregateQuery } from "./src/decorators";

@FactTable({
  name: "tf_sales",
  measures: ["revenue", "quantity"],
  dimensionColumn: "dimensions"
})
class SalesFactTable {
  revenue!: number;
  quantity!: number;
}

@AggregateQuery(factTable = "tf_sales")
salesByCategory(category: string): Record<string, any> {
  return {};
}
```text
<!-- Code example in TEXT -->

### Configuration

Enable experimental decorators in `tsconfig.json`:

```json
<!-- Code example in JSON -->
{
  "compilerOptions": {
    "experimentalDecorators": true,
    "emitDecoratorMetadata": true,
    "target": "ES2022"
  }
}
```text
<!-- Code example in TEXT -->

### Features

- ✅ Full TypeScript type safety
- ✅ Decorator-based schema definition
- ✅ Analytics support
- ✅ Jest testing support
- ✅ JSON schema export
- ✅ CLI compilation support

### Testing

```bash
<!-- Code example in BASH -->
cd FraiseQL-typescript
npm test

# E2E test
npm run example:basic
npm run example:analytics
```text
<!-- Code example in TEXT -->

## Go Generator

### Installation

```bash
<!-- Code example in BASH -->
cd FraiseQL-go
go mod download
```text
<!-- Code example in TEXT -->

### Basic Usage

```go
<!-- Code example in Go -->
package main

import "github.com/FraiseQL/FraiseQL-go/FraiseQL"

// Define types
type User struct {
    ID        int     `FraiseQL:"id"`
    Name      string  `FraiseQL:"name"`
    Email     *string `FraiseQL:"email"`
    CreatedAt string  `FraiseQL:"createdAt"`
    IsActive  bool    `FraiseQL:"isActive"`
}

type Post struct {
    ID        int    `FraiseQL:"id"`
    Title     string `FraiseQL:"title"`
    Content   string `FraiseQL:"content"`
    AuthorID  int    `FraiseQL:"authorId"`
    Published bool   `FraiseQL:"published"`
}

// Define schema
type Schema struct {
    Users []User `FraiseQL:"query,sql_source=v_users"`
    Posts []Post `FraiseQL:"query,sql_source=v_posts"`
}

// Export schema
func main() {
    FraiseQL.ExportSchema("schema.json")
}
```text
<!-- Code example in TEXT -->

### Features

- ✅ Struct-based type definition
- ✅ Tag-based configuration
- ✅ Nil pointer for nullable fields
- ✅ JSON schema export
- ✅ CLI compilation support
- ✅ High performance

### Testing

```bash
<!-- Code example in BASH -->
cd FraiseQL-go
go test ./FraiseQL/... -v

# Run example
go run examples/basic_schema.go
```text
<!-- Code example in TEXT -->

## Java Generator

### Installation

```bash
<!-- Code example in BASH -->
cd FraiseQL-java
mvn clean install
```text
<!-- Code example in TEXT -->

### Basic Usage

```java
<!-- Code example in Java -->
package com.FraiseQL.example;

import com.FraiseQL.annotations.*;
import java.util.List;

@FraiseQLType
public class User {
    @Field
    private int id;

    @Field
    private String name;

    @Field(nullable = true)
    private String email;

    // Getters/setters...
}

@FraiseQLType
public class Post {
    @Field
    private int id;

    @Field
    private String title;

    @Field(sqlSource = "v_posts")
    private List<Post> posts;
}

public class Schema {
    @Query(sqlSource = "v_users")
    public List<User> users(int limit) {
        return null;
    }

    @Mutation(sqlSource = "fn_create_user")
    public User createUser(String name, String email) {
        return null;
    }
}
```text
<!-- Code example in TEXT -->

### Features

- ✅ Annotation-based schema definition
- ✅ Full type safety with generics
- ✅ Stream API integration
- ✅ JSON schema export
- ✅ CLI compilation support

### Testing

```bash
<!-- Code example in BASH -->
cd FraiseQL-java
mvn test
```text
<!-- Code example in TEXT -->

## PHP Generator

### Installation

```bash
<!-- Code example in BASH -->
cd FraiseQL-php
composer install
```text
<!-- Code example in TEXT -->

### Basic Usage

```php
<!-- Code example in PHP -->
<?php

namespace FraiseQL\Example;

use FraiseQL\Attributes\Type;
use FraiseQL\Attributes\Field;
use FraiseQL\Attributes\Query;

#[Type]
class User {
    #[Field]
    public int $id;

    #[Field]
    public string $name;

    #[Field(nullable: true)]
    public ?string $email;
}

#[Type]
class Post {
    #[Field]
    public int $id;

    #[Field]
    public string $title;
}

class Schema {
    #[Query(sqlSource: 'v_users')]
    public function users(int $limit = 10): array {
        return [];
    }

    #[Query(sqlSource: 'v_posts')]
    public function posts(int $authorId = null): array {
        return [];
    }
}

// Export schema
(new SchemaExporter())->export('schema.json');
?>
```text
<!-- Code example in TEXT -->

### Features

- ✅ PHP 8 Attributes-based schema definition
- ✅ Full type declaration support
- ✅ Nullable type support
- ✅ JSON schema export
- ✅ CLI compilation support

### Testing

```bash
<!-- Code example in BASH -->
cd FraiseQL-php
vendor/bin/phpunit tests/
```text
<!-- Code example in TEXT -->

## Schema Generation Workflow

### Step 1: Define Schema in Language

Use language-specific decorators/annotations to define types, queries, and mutations.

### Step 2: Generate JSON

All generators export to `schema.json`:

```python
<!-- Code example in Python -->
fraiseql_schema.export_schema("schema.json")
```text
<!-- Code example in TEXT -->

### Step 3: Compile with CLI

```bash
<!-- Code example in BASH -->
FraiseQL-cli compile schema.json
```text
<!-- Code example in TEXT -->

This produces `schema.compiled.json` with:

- Optimized SQL templates
- Type validation
- Performance suggestions

### Step 4: Deploy Compiled Schema

Use compiled schema with runtime:

```bash
<!-- Code example in BASH -->
FraiseQL-server --schema schema.compiled.json
```text
<!-- Code example in TEXT -->

## Feature Comparison

| Feature | Python | TypeScript | Go | Java | PHP |
|---------|--------|------------|----|----- |-----|
| Basic types | ✅ | ✅ | ✅ | ✅ | ✅ |
| Nullable fields | ✅ | ✅ | ✅ | ✅ | ✅ |
| List types | ✅ | ✅ | ✅ | ✅ | ✅ |
| Queries | ✅ | ✅ | ✅ | ✅ | ✅ |
| Mutations | ✅ | ✅ | ✅ | ✅ | ✅ |
| Fact tables | ✅ | ✅ | ⏳ | ⏳ | ⏳ |
| Aggregate queries | ✅ | ✅ | ⏳ | ⏳ | ⏳ |
| Custom scalars | ✅ | ✅ | ✅ | ✅ | ✅ |
| Subscriptions | ⏳ | ⏳ | ⏳ | ⏳ | ⏳ |

## Best Practices

### 1. Use Consistent Naming

```python
<!-- Code example in Python -->
# Good: Clear, descriptive names
@fraiseql_type
class UserProfile:
    userId: int
    displayName: str

# Avoid: Vague or abbreviated names
@fraiseql_type
class U:
    uid: UUID  # UUID v4 for GraphQL ID
    nm: str
```text
<!-- Code example in TEXT -->

### 2. Leverage Type Safety

```typescript
<!-- Code example in TypeScript -->
// Good: Full type annotations
@Query(sql_source = "v_users")
users(limit: number, offset: number): User[] {
  return [];
}

// Avoid: Any types
@Query(sql_source = "v_users")
users(limit: any, offset: any): any[] {
  return [];
}
```text
<!-- Code example in TEXT -->

### 3. Document Complex Schemas

```go
<!-- Code example in Go -->
// Good: Document purpose and constraints
type SalesAnalytics struct {
    // Revenue in cents for precision
    Revenue int `FraiseQL:"revenue,description=Revenue in cents"`
    // Aggregated by date
    Date string `FraiseQL:"date,description=Date in YYYY-MM-DD format"`
}

// Avoid: Undocumented fields
type SalesData struct {
    Rev int
    D string
}
```text
<!-- Code example in TEXT -->

### 4. Test Before Compilation

```bash
<!-- Code example in BASH -->
# Run language-specific tests first
go test ./FraiseQL/...
npm test --prefix FraiseQL-typescript

# Then compile
FraiseQL-cli compile schema.json
```text
<!-- Code example in TEXT -->

## Performance Considerations

- **Python**: Decorator application happens at import time
- **TypeScript**: Metadata stored in memory during execution
- **Go**: Reflection-based, zero runtime cost after initial schema extraction
- **Java**: Annotation processing at compile time
- **PHP**: Reflection-based, attributes extracted at first use

## Troubleshooting

### "Type not found" Error

**Cause**: Schema references undefined type

**Solution**: Ensure all types are decorated/annotated and exported

### "SQL source not valid" Error

**Cause**: sql_source references non-existent database object

**Solution**: Verify database schema or use validation-only mode

### Export produces empty schema

**Cause**: Types not registered with schema registry

**Solution**: Ensure all classes are decorated/annotated and in scope

## Migration Guide

### From REST APIs

1. Define types matching API response structures
2. Map API endpoints to queries/mutations
3. Export schema and compile

### From Other GraphQL Implementations

1. Replicate type definitions in FraiseQL schema
2. Map resolvers to sql_source references
3. Export and compile

## See Also

- [CLI Schema Format Guide](../reference/cli-schema-format.md)
- [FraiseQL Guides](./README.md)

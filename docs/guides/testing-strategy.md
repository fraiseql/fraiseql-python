<!-- Skip to main content -->
---

title: FraiseQL Testing Strategy: Comprehensive Guide to Testing Compiled GraphQL Systems
description: 1. [Executive Summary](#executive-summary)
keywords: ["debugging", "implementation", "best-practices", "deployment", "graphql", "tutorial"]
tags: ["documentation", "reference"]
---

# FraiseQL Testing Strategy: Comprehensive Guide to Testing Compiled GraphQL Systems

**Status:** ✅ Production Ready
**Audience:** Developers, QA Engineers, DevOps
**Reading Time:** 20-30 minutes
**Last Updated:** 2026-02-05

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Unit Testing Strategy](#1-unit-testing-strategy)
3. [Integration Testing Strategy](#2-integration-testing-strategy)
4. [End-to-End Testing Strategy](#3-end-to-end-e2e-testing-strategy)
5. [Test Data Management](#4-test-data-management)
6. [CI/CD Testing Pipeline](#5-cicd-testing-pipeline)
7. [Testing Best Practices](#6-testing-best-practices)
8. [Continuous Testing](#7-continuous-testing)

---

## Executive Summary

FraiseQL's testing strategy is **layered and deterministic**, mirroring its compilation architecture. Because FraiseQL compiles schemas to deterministic execution plans, testing focuses on:

1. **Compile-time correctness** — Schema validation, type closure, binding verification
2. **Runtime correctness** — Query execution, authorization enforcement, result projection
3. **Database integration** — View correctness, stored procedure behavior, CDC events
4. **End-to-end behavior** — Client workflows, performance characteristics, error handling

**Core principle:** Test determinism at every layer. Same inputs → same outputs, always.

**Testing pyramid:**

```text
<!-- Code example in TEXT -->
                    ▲
                   / \
                  /   \
                 / E2E \          10% — End-to-end tests (100-200 tests)
                /───────\
               /  Integ  \        30% — Integration tests (500-800 tests)
              /───────────\
             /    Unit     \      60% — Unit tests (1000-2000 tests)
            /───────────────\
           ───────────────────
```text
<!-- Code example in TEXT -->

**Target metrics:**

- **Coverage:** 95%+ line coverage, 90%+ branch coverage
- **Speed:** Unit tests <1s total, integration tests <30s total, E2E tests <5min total
- **Reliability:** 0% flaky tests (deterministic execution = deterministic tests)
- **Regression:** All bugs get regression tests before fix

---

## 1. Unit Testing Strategy

### 1.1 Compiler Unit Tests (Python SDK)

**What to test:** Individual compilation phases in isolation

**Directory:** `tests/unit/compiler/`

#### 1.1.1 Schema Parsing Tests

Test IR generation from authoring languages:

```python
<!-- Code example in Python -->
# tests/unit/compiler/test_schema_parsing.py
import pytest
from FraiseQL.compiler.parser import parse_schema
from FraiseQL.compiler.ir import SchemaIR, TypeDef, QueryDef

def test_parse_simple_type():
    """Test parsing a simple @FraiseQL.type decorated class."""
    schema_source = '''
import FraiseQL

@FraiseQL.type
class User:
    """A user account."""
    id: UUID  # UUID v4 for GraphQL ID
    username: str
    email: str
    '''

    ir: SchemaIR = parse_schema(schema_source, language="python")

    assert "User" in ir.types
    user_type = ir.types["User"]
    assert user_type.name == "User"
    assert user_type.kind == "OBJECT"
    assert "id" in user_type.fields
    assert user_type.fields["id"].graphql_type == "String!"


def test_parse_query_with_arguments():
    """Test parsing @FraiseQL.query with arguments."""
    schema_source = '''
import FraiseQL

@FraiseQL.query
def user(id: str) -> User:
    """Get user by ID."""
    pass
    '''

    ir: SchemaIR = parse_schema(schema_source, language="python")

    assert "user" in ir.queries
    query = ir.queries["user"]
    assert query.name == "user"
    assert "id" in query.arguments
    assert query.arguments["id"].type == "String!"
    assert query.return_type == "User"


def test_parse_mutation_with_input():
    """Test parsing @FraiseQL.mutation with input type."""
    schema_source = '''
import FraiseQL

@FraiseQL.input
class CreateUserInput:
    username: str
    email: str
    password: str

@FraiseQL.mutation
def create_user(input: CreateUserInput) -> User:
    """Create a new user."""
    pass
    '''

    ir: SchemaIR = parse_schema(schema_source, language="python")

    assert "CreateUserInput" in ir.types
    assert "create_user" in ir.mutations
    mutation = ir.mutations["create_user"]
    assert "input" in mutation.arguments
    assert mutation.arguments["input"].type == "CreateUserInput!"


@pytest.mark.parametrize("invalid_source,expected_error", [
    (
        # Missing return type
        "@FraiseQL.query\ndef users():\n    pass",
        "E_SCHEMA_QUERY_NO_RETURN_TYPE_001"
    ),
    (
        # Invalid type hint
        "@FraiseQL.type\nclass User:\n    id: NotAType",
        "E_SCHEMA_TYPE_UNDEFINED_002"
    ),
    (
        # Duplicate type name
        "@FraiseQL.type\nclass User:\n    pass\n@FraiseQL.type\nclass User:\n    pass",
        "E_SCHEMA_DUPLICATE_TYPE_003"
    ),
])
def test_parse_invalid_schema(invalid_source, expected_error):
    """Test that invalid schemas produce correct error codes."""
    with pytest.raises(CompilationError) as exc_info:
        parse_schema(invalid_source, language="python")

    assert exc_info.value.code == expected_error
```text
<!-- Code example in TEXT -->

#### 1.1.2 Database Introspection Tests

Test introspection against mock database metadata:

```python
<!-- Code example in Python -->
# tests/unit/compiler/test_introspection.py
import pytest
from FraiseQL.compiler.introspection import DatabaseIntrospector
from FraiseQL.compiler.capabilities import CapabilityManifest

@pytest.fixture
def mock_db_metadata():
    """Mock database metadata (views, columns, procedures)."""
    return {
        "views": {
            "v_user": {
                "columns": [
                    {"name": "id", "type": "uuid", "nullable": False},
                    {"name": "data", "type": "jsonb", "nullable": False},
                ],
                "owner": "api_user",
            },
            "v_post": {
                "columns": [
                    {"name": "id", "type": "uuid", "nullable": False},
                    {"name": "user_id", "type": "uuid", "nullable": False},
                    {"name": "data", "type": "jsonb", "nullable": False},
                ],
                "owner": "api_user",
            },
        },
        "procedures": {
            "fn_create_user": {
                "parameters": [
                    {"name": "username", "type": "text"},
                    {"name": "email", "type": "text"},
                    {"name": "password_hash", "type": "text"},
                ],
                "returns": "jsonb",
            },
        },
    }


def test_introspect_view_columns(mock_db_metadata):
    """Test introspection discovers view columns correctly."""
    introspector = DatabaseIntrospector(mock_db_metadata)

    columns = introspector.get_view_columns("v_user")

    assert len(columns) == 2
    assert columns[0].name == "id"
    assert columns[0].db_type == "uuid"
    assert columns[0].nullable is False
    assert columns[1].name == "data"
    assert columns[1].db_type == "jsonb"


def test_introspect_procedure_signature(mock_db_metadata):
    """Test introspection discovers procedure signatures."""
    introspector = DatabaseIntrospector(mock_db_metadata)

    signature = introspector.get_procedure_signature("fn_create_user")

    assert len(signature.parameters) == 3
    assert signature.parameters[0].name == "username"
    assert signature.parameters[0].type == "text"
    assert signature.returns == "jsonb"


def test_generate_capability_manifest(mock_db_metadata):
    """Test capability manifest generation."""
    introspector = DatabaseIntrospector(mock_db_metadata)

    manifest: CapabilityManifest = introspector.generate_capabilities()

    # Check column operators discovered from database type
    assert "uuid" in manifest.column_types
    uuid_ops = manifest.column_types["uuid"].operators
    assert "eq" in uuid_ops
    assert "in" in uuid_ops
    assert "is_null" in uuid_ops

    # Check JSONB operators
    assert "jsonb" in manifest.column_types
    jsonb_ops = manifest.column_types["jsonb"].operators
    assert "contains" in jsonb_ops
    assert "has_key" in jsonb_ops
```text
<!-- Code example in TEXT -->

#### 1.1.3 Type Binding Tests

Test GraphQL type → database view binding:

```python
<!-- Code example in Python -->
# tests/unit/compiler/test_type_binding.py
import pytest
from FraiseQL.compiler.binder import TypeBinder
from FraiseQL.compiler.ir import SchemaIR, TypeDef, FieldDef, BindingDef

def test_bind_type_to_view():
    """Test binding a GraphQL type to a database view."""
    schema_ir = SchemaIR(
        types={
            "User": TypeDef(
                name="User",
                kind="OBJECT",
                fields={
                    "id": FieldDef(name="id", graphql_type="ID!"),
                    "username": FieldDef(name="username", graphql_type="String!"),
                    "email": FieldDef(name="email", graphql_type="String!"),
                }
            )
        },
        bindings={
            "User": BindingDef(
                type_name="User",
                binding_type="VIEW",
                view_name="v_user",
                data_column="data",
            )
        }
    )

    db_metadata = {
        "views": {
            "v_user": {
                "columns": [
                    {"name": "id", "type": "uuid"},
                    {"name": "data", "type": "jsonb"},
                ]
            }
        }
    }

    binder = TypeBinder(schema_ir, db_metadata)
    bound_schema = binder.bind()

    # Verify binding succeeded
    assert "User" in bound_schema.types
    user_type = bound_schema.types["User"]
    assert user_type.binding.view_name == "v_user"
    assert user_type.binding.data_column == "data"

    # Verify field paths resolved
    assert user_type.fields["id"].jsonb_path == ["id"]
    assert user_type.fields["username"].jsonb_path == ["username"]


def test_bind_type_missing_view():
    """Test binding fails when view doesn't exist."""
    schema_ir = SchemaIR(
        types={"User": TypeDef(name="User", kind="OBJECT", fields={})},
        bindings={
            "User": BindingDef(
                type_name="User",
                binding_type="VIEW",
                view_name="v_user_missing",  # Doesn't exist
            )
        }
    )

    db_metadata = {"views": {}}

    binder = TypeBinder(schema_ir, db_metadata)

    with pytest.raises(BindingError) as exc_info:
        binder.bind()

    assert exc_info.value.code == "E_BINDING_VIEW_NOT_FOUND_010"
    assert "v_user_missing" in str(exc_info.value)


def test_bind_nested_type():
    """Test binding nested types (User.posts -> v_posts_by_user)."""
    schema_ir = SchemaIR(
        types={
            "User": TypeDef(
                name="User",
                kind="OBJECT",
                fields={
                    "id": FieldDef(name="id", graphql_type="ID!"),
                    "posts": FieldDef(name="posts", graphql_type="[Post!]!"),
                }
            ),
            "Post": TypeDef(
                name="Post",
                kind="OBJECT",
                fields={
                    "id": FieldDef(name="id", graphql_type="ID!"),
                    "title": FieldDef(name="title", graphql_type="String!"),
                }
            )
        },
        bindings={
            "User": BindingDef(
                type_name="User",
                binding_type="VIEW",
                view_name="v_user",
            ),
            "User.posts": BindingDef(
                type_name="User",
                field_name="posts",
                binding_type="VIEW",
                view_name="v_posts_by_user",
                parent_key="user_id",
            )
        }
    )

    db_metadata = {
        "views": {
            "v_user": {"columns": [{"name": "id", "type": "uuid"}, {"name": "data", "type": "jsonb"}]},
            "v_posts_by_user": {"columns": [{"name": "user_id", "type": "uuid"}, {"name": "data", "type": "jsonb"}]},
        }
    }

    binder = TypeBinder(schema_ir, db_metadata)
    bound_schema = binder.bind()

    # Verify nested binding
    user_type = bound_schema.types["User"]
    posts_field = user_type.fields["posts"]
    assert posts_field.binding.view_name == "v_posts_by_user"
    assert posts_field.binding.parent_key == "user_id"
```text
<!-- Code example in TEXT -->

#### 1.1.4 WHERE Type Generation Tests

Test auto-generation of WHERE input types from database capabilities:

```python
<!-- Code example in Python -->
# tests/unit/compiler/test_where_generation.py
import pytest
from FraiseQL.compiler.where_gen import WhereTypeGenerator
from FraiseQL.compiler.capabilities import CapabilityManifest, ColumnType, Operator

def test_generate_where_type_for_string_column():
    """Test WHERE type generation for string columns."""
    manifest = CapabilityManifest(
        column_types={
            "text": ColumnType(
                db_type="text",
                graphql_type="String",
                operators=[
                    Operator(name="eq", graphql_name="eq", signature="String"),
                    Operator(name="ne", graphql_name="ne", signature="String"),
                    Operator(name="like", graphql_name="like", signature="String"),
                    Operator(name="in", graphql_name="in", signature="[String!]"),
                    Operator(name="is_null", graphql_name="isNull", signature="Boolean"),
                ]
            )
        }
    )

    generator = WhereTypeGenerator(manifest)
    where_type = generator.generate_where_type("username", "text")

    assert where_type.name == "StringWhereInput"
    assert "eq" in where_type.fields
    assert where_type.fields["eq"].graphql_type == "String"
    assert "like" in where_type.fields
    assert "in" in where_type.fields
    assert where_type.fields["in"].graphql_type == "[String!]"
    assert "isNull" in where_type.fields


def test_generate_where_type_for_int_column():
    """Test WHERE type generation for integer columns."""
    manifest = CapabilityManifest(
        column_types={
            "integer": ColumnType(
                db_type="integer",
                graphql_type="Int",
                operators=[
                    Operator(name="eq", graphql_name="eq", signature="Int"),
                    Operator(name="gt", graphql_name="gt", signature="Int"),
                    Operator(name="gte", graphql_name="gte", signature="Int"),
                    Operator(name="lt", graphql_name="lt", signature="Int"),
                    Operator(name="lte", graphql_name="lte", signature="Int"),
                    Operator(name="in", graphql_name="in", signature="[Int!]"),
                ]
            )
        }
    )

    generator = WhereTypeGenerator(manifest)
    where_type = generator.generate_where_type("age", "integer")

    assert where_type.name == "IntWhereInput"
    assert "eq" in where_type.fields
    assert "gt" in where_type.fields
    assert "gte" in where_type.fields
    assert "lt" in where_type.fields
    assert "lte" in where_type.fields
    assert "in" in where_type.fields


def test_generate_where_type_for_uuid_column():
    """Test WHERE type generation for UUID columns."""
    manifest = CapabilityManifest(
        column_types={
            "uuid": ColumnType(
                db_type="uuid",
                graphql_type="ID",
                operators=[
                    Operator(name="eq", graphql_name="eq", signature="ID"),
                    Operator(name="ne", graphql_name="ne", signature="ID"),
                    Operator(name="in", graphql_name="in", signature="[ID!]"),
                ]
            )
        }
    )

    generator = WhereTypeGenerator(manifest)
    where_type = generator.generate_where_type("id", "uuid")

    assert where_type.name == "IDWhereInput"
    assert "eq" in where_type.fields
    assert "ne" in where_type.fields
    assert "in" in where_type.fields
    # No gt/lt operators for UUID
    assert "gt" not in where_type.fields
    assert "lt" not in where_type.fields
```text
<!-- Code example in TEXT -->

#### 1.1.5 Validation Tests

Test schema validation rules:

```python
<!-- Code example in Python -->
# tests/unit/compiler/test_validation.py
import pytest
from FraiseQL.compiler.validator import SchemaValidator
from FraiseQL.compiler.ir import SchemaIR, TypeDef, QueryDef, BindingDef

def test_validate_type_closure():
    """Test type closure validation (all referenced types are defined)."""
    schema_ir = SchemaIR(
        types={
            "User": TypeDef(name="User", kind="OBJECT", fields={}),
            # Post type is referenced but not defined
        },
        queries={
            "user": QueryDef(name="user", return_type="User"),
            "posts": QueryDef(name="posts", return_type="[Post!]!"),  # Post not defined
        }
    )

    validator = SchemaValidator(schema_ir)

    with pytest.raises(ValidationError) as exc_info:
        validator.validate()

    assert exc_info.value.code == "E_SCHEMA_TYPE_NOT_DEFINED_001"
    assert "Post" in str(exc_info.value)


def test_validate_binding_completeness():
    """Test all queries have bindings."""
    schema_ir = SchemaIR(
        types={"User": TypeDef(name="User", kind="OBJECT", fields={})},
        queries={
            "user": QueryDef(name="user", return_type="User"),
            "posts": QueryDef(name="posts", return_type="[Post!]!"),
        },
        bindings={
            "user": BindingDef(query_name="user", view_name="v_user"),
            # 'posts' query has no binding
        }
    )

    validator = SchemaValidator(schema_ir)

    with pytest.raises(ValidationError) as exc_info:
        validator.validate()

    assert exc_info.value.code == "E_SCHEMA_BINDING_MISSING_003"
    assert "posts" in str(exc_info.value)


def test_validate_authorization_context():
    """Test authorization rules reference valid context fields."""
    schema_ir = SchemaIR(
        auth_context={
            "user_id": "String!",
            "roles": "[String!]!",
        },
        auth_rules=[
            AuthRule(
                query="users",
                requires_auth=True,
                requires_role=["admin"],  # Valid
            ),
            AuthRule(
                query="posts",
                requires_claim={"department": "engineering"},  # Invalid: 'department' not in auth context
            ),
        ]
    )

    validator = SchemaValidator(schema_ir)

    with pytest.raises(ValidationError) as exc_info:
        validator.validate()

    assert exc_info.value.code == "E_SCHEMA_AUTHORIZATION_INVALID_005"
    assert "department" in str(exc_info.value)
```text
<!-- Code example in TEXT -->

#### 1.1.6 Compilation Tests

Test full compilation pipeline:

```python
<!-- Code example in Python -->
# tests/unit/compiler/test_compilation.py
import pytest
from FraiseQL.compiler import compile_schema
from FraiseQL.compiler.ir import CompiledSchema

def test_compile_simple_schema(db_connection):
    """Test compiling a simple schema end-to-end."""
    schema_source = '''
import FraiseQL

@FraiseQL.type
class User:
    id: UUID  # UUID v4 for GraphQL ID
    username: str
    email: str

@FraiseQL.query
def user(id: str) -> User:
    """Get user by ID."""
    pass

@FraiseQL.query
def users(where: UserWhereInput | None = None) -> list[User]:
    """List users with optional filtering."""
    pass

@FraiseQL.binding("user", view="v_user", where_column="id")
@FraiseQL.binding("users", view="v_user")
class UserBindings:
    pass
    '''

    compiled = compile_schema(
        source=schema_source,
        language="python",
        database=db_connection,
        target="postgresql"
    )

    assert isinstance(compiled, CompiledSchema)
    assert compiled.version == "1.0"
    assert "User" in compiled.types
    assert "user" in compiled.queries
    assert "users" in compiled.queries

    # Check WHERE type was auto-generated
    assert "UserWhereInput" in compiled.types
    user_where = compiled.types["UserWhereInput"]
    assert user_where.kind == "INPUT"

    # Check bindings
    assert compiled.bindings["user"].view_name == "v_user"
    assert compiled.bindings["user"].where_column == "id"


def test_compile_schema_with_mutations(db_connection):
    """Test compiling schema with mutations."""
    schema_source = '''
import FraiseQL

@FraiseQL.input
class CreateUserInput:
    username: str
    email: str
    password: str

@FraiseQL.mutation
def create_user(input: CreateUserInput) -> User:
    """Create a new user."""
    pass

@FraiseQL.binding("create_user", procedure="fn_create_user")
class Bindings:
    pass
    '''

    compiled = compile_schema(
        source=schema_source,
        language="python",
        database=db_connection,
        target="postgresql"
    )

    assert "create_user" in compiled.mutations
    mutation = compiled.mutations["create_user"]
    assert mutation.binding.procedure_name == "fn_create_user"
    assert "input" in mutation.arguments
```text
<!-- Code example in TEXT -->

### 1.2 Runtime Unit Tests (Rust)

**What to test:** Individual runtime components in isolation

**Directory:** `tests/unit/runtime/`

#### 1.2.1 Query Parsing Tests

```rust
<!-- Code example in RUST -->
// tests/unit/runtime/test_query_parsing.rs
use fraiseql_runtime::parser::parse_graphql_query;
use fraiseql_runtime::query::Query;

#[test]
fn test_parse_simple_query() {
    let query_str = r#"
        query GetUser {
            user(id: "123") {
                id
                username
                email
            }
        }
    "#;

    let query = parse_graphql_query(query_str).unwrap();

    assert_eq!(query.operation_name, Some("GetUser".to_string()));
    assert_eq!(query.operation_type, OperationType::Query);
    assert_eq!(query.selections.len(), 1);

    let user_field = &query.selections[0];
    assert_eq!(user_field.name, "user");
    assert_eq!(user_field.arguments.len(), 1);
    assert_eq!(user_field.arguments["id"], Value::String("123".to_string()));
}

#[test]
fn test_parse_query_with_variables() {
    let query_str = r#"
        query GetUser($userId: ID!) {
            user(id: $userId) {
                id
                username
            }
        }
    "#;

    let variables = serde_json::json!({
        "userId": "456"
    });

    let query = parse_graphql_query(query_str).unwrap();
    let bound_query = query.bind_variables(&variables).unwrap();

    let user_field = &bound_query.selections[0];
    assert_eq!(user_field.arguments["id"], Value::String("456".to_string()));
}

#[test]
fn test_parse_query_with_fragments() {
    let query_str = r#"
        fragment UserFields on User {
            id
            username
            email
        }

        query GetUser {
            user(id: "123") {
                ...UserFields
            }
        }
    "#;

    let query = parse_graphql_query(query_str).unwrap();

    assert_eq!(query.fragments.len(), 1);
    assert!(query.fragments.contains_key("UserFields"));
}

#[test]
fn test_parse_invalid_query() {
    let invalid_query = "query { user( }";  // Syntax error

    let result = parse_graphql_query(invalid_query);

    assert!(result.is_err());
    let err = result.unwrap_err();
    assert_eq!(err.code, "E_RUNTIME_QUERY_PARSE_ERROR_100");
}
```text
<!-- Code example in TEXT -->

#### 1.2.2 Authorization Tests

```rust
<!-- Code example in RUST -->
// tests/unit/runtime/test_authorization.rs
use fraiseql_runtime::auth::{AuthContext, AuthRule, enforce_authorization};

#[test]
fn test_enforce_requires_auth() {
    let auth_rule = AuthRule {
        requires_auth: true,
        requires_role: None,
        requires_claim: None,
    };

    // Authenticated user
    let auth_context = AuthContext {
        user_id: Some("user-123".to_string()),
        roles: vec![],
        claims: HashMap::new(),
        authenticated: true,
    };

    let result = enforce_authorization(&auth_rule, &auth_context);
    assert!(result.is_ok());

    // Unauthenticated user
    let unauth_context = AuthContext {
        user_id: None,
        roles: vec![],
        claims: HashMap::new(),
        authenticated: false,
    };

    let result = enforce_authorization(&auth_rule, &unauth_context);
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code, "E_RUNTIME_AUTH_UNAUTHENTICATED_200");
}

#[test]
fn test_enforce_requires_role() {
    let auth_rule = AuthRule {
        requires_auth: true,
        requires_role: Some(vec!["admin".to_string()]),
        requires_claim: None,
    };

    // User with admin role
    let admin_context = AuthContext {
        user_id: Some("user-123".to_string()),
        roles: vec!["admin".to_string(), "user".to_string()],
        claims: HashMap::new(),
        authenticated: true,
    };

    let result = enforce_authorization(&auth_rule, &admin_context);
    assert!(result.is_ok());

    // User without admin role
    let user_context = AuthContext {
        user_id: Some("user-456".to_string()),
        roles: vec!["user".to_string()],
        claims: HashMap::new(),
        authenticated: true,
    };

    let result = enforce_authorization(&auth_rule, &user_context);
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code, "E_RUNTIME_AUTH_FORBIDDEN_201");
}

#[test]
fn test_enforce_requires_claim() {
    let auth_rule = AuthRule {
        requires_auth: true,
        requires_role: None,
        requires_claim: Some(HashMap::from([
            ("department".to_string(), "engineering".to_string()),
        ])),
    };

    // User with matching claim
    let matching_context = AuthContext {
        user_id: Some("user-123".to_string()),
        roles: vec![],
        claims: HashMap::from([
            ("department".to_string(), "engineering".to_string()),
        ]),
        authenticated: true,
    };

    let result = enforce_authorization(&auth_rule, &matching_context);
    assert!(result.is_ok());

    // User with different claim value
    let non_matching_context = AuthContext {
        user_id: Some("user-456".to_string()),
        roles: vec![],
        claims: HashMap::from([
            ("department".to_string(), "sales".to_string()),
        ]),
        authenticated: true,
    };

    let result = enforce_authorization(&auth_rule, &non_matching_context);
    assert!(result.is_err());
}
```text
<!-- Code example in TEXT -->

#### 1.2.3 Query Planning Tests

```rust
<!-- Code example in RUST -->
// tests/unit/runtime/test_query_planning.rs
use fraiseql_runtime::planner::{QueryPlanner, ExecutionPlan};
use fraiseql_runtime::schema::CompiledSchema;

#[test]
fn test_plan_simple_query() {
    let compiled_schema = load_test_schema("simple_user_schema.json");
    let planner = QueryPlanner::new(&compiled_schema);

    let query = parse_query(r#"
        query {
            user(id: "123") {
                id
                username
            }
        }
    "#);

    let plan = planner.plan(&query).unwrap();

    assert_eq!(plan.steps.len(), 1);
    assert_eq!(plan.steps[0].view_name, "v_user");
    assert_eq!(plan.steps[0].where_clause, Some("id = $1".to_string()));
    assert_eq!(plan.steps[0].parameters, vec![Value::String("123".to_string())]);
}

#[test]
fn test_plan_nested_query() {
    let compiled_schema = load_test_schema("user_posts_schema.json");
    let planner = QueryPlanner::new(&compiled_schema);

    let query = parse_query(r#"
        query {
            user(id: "123") {
                id
                username
                posts {
                    id
                    title
                }
            }
        }
    "#);

    let plan = planner.plan(&query).unwrap();

    // Should generate 1 database call (v_user already has posts pre-aggregated)
    assert_eq!(plan.steps.len(), 1);
    assert_eq!(plan.steps[0].view_name, "v_user");

    // Check JSONB path selection
    let jsonb_select = &plan.steps[0].jsonb_select;
    assert!(jsonb_select.contains(&"posts".to_string()));
}

#[test]
fn test_plan_query_with_where_filter() {
    let compiled_schema = load_test_schema("user_schema.json");
    let planner = QueryPlanner::new(&compiled_schema);

    let query = parse_query(r#"
        query {
            users(where: { username: { like: "john%" } }) {
                id
                username
            }
        }
    "#);

    let plan = planner.plan(&query).unwrap();

    assert_eq!(plan.steps.len(), 1);
    assert!(plan.steps[0].where_clause.as_ref().unwrap().contains("username LIKE"));
    assert_eq!(plan.steps[0].parameters, vec![Value::String("john%".to_string())]);
}
```text
<!-- Code example in TEXT -->

#### 1.2.4 Result Projection Tests

```rust
<!-- Code example in RUST -->
// tests/unit/runtime/test_projection.rs
use fraiseql_runtime::projection::project_result;
use serde_json::json;

#[test]
fn test_project_simple_fields() {
    let db_result = json!({
        "id": "user-123",
        "data": {
            "id": "user-123",
            "username": "alice",
            "email": "alice@example.com",
            "password_hash": "secret"
        }
    });

    let selection = vec!["id", "username", "email"];

    let projected = project_result(&db_result, &selection).unwrap();

    assert_eq!(projected["id"], "user-123");
    assert_eq!(projected["username"], "alice");
    assert_eq!(projected["email"], "alice@example.com");
    assert!(!projected.as_object().unwrap().contains_key("password_hash"));
}

#[test]
fn test_project_nested_fields() {
    let db_result = json!({
        "id": "user-123",
        "data": {
            "id": "user-123",
            "username": "alice",
            "posts": [
                {"id": "post-1", "title": "First post"},
                {"id": "post-2", "title": "Second post"}
            ]
        }
    });

    let selection = json!({
        "id": true,
        "username": true,
        "posts": {
            "id": true,
            "title": true
        }
    });

    let projected = project_result(&db_result, &selection).unwrap();

    assert_eq!(projected["username"], "alice");
    assert_eq!(projected["posts"].as_array().unwrap().len(), 2);
    assert_eq!(projected["posts"][0]["title"], "First post");
}

#[test]
fn test_project_with_field_masking() {
    let db_result = json!({
        "id": "user-123",
        "data": {
            "id": "user-123",
            "email": "alice@example.com",
            "ssn": "123-45-6789"
        }
    });

    let selection = vec!["id", "email", "ssn"];
    let field_masks = vec!["ssn"];  // ssn field is masked for this user

    let projected = project_result_with_masks(&db_result, &selection, &field_masks).unwrap();

    assert_eq!(projected["email"], "alice@example.com");
    assert!(projected["ssn"].is_null());  // Masked field returns null
}
```text
<!-- Code example in TEXT -->

---

## 2. Integration Testing Strategy

### 2.1 Compiler Integration Tests

**What to test:** Compiler against real database

**Directory:** `tests/integration/compiler/`

#### 2.1.1 End-to-End Compilation Tests

```python
<!-- Code example in Python -->
# tests/integration/compiler/test_compilation_e2e.py
import pytest
from FraiseQL.compiler import compile_schema
from FraiseQL.testing import DatabaseFixture

@pytest.fixture
def test_db():
    """Create test database with schema."""
    db = DatabaseFixture()
    db.execute_sql("""
        CREATE TABLE tb_user (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE VIEW v_user AS
        SELECT
            id,
            jsonb_build_object(
                'id', id::text,
                'username', username,
                'email', email,
                'createdAt', created_at,
                'updatedAt', updated_at
            ) AS data
        FROM tb_user;

        CREATE FUNCTION fn_create_user(
            p_username TEXT,
            p_email TEXT,
            p_password_hash TEXT
        ) RETURNS JSONB AS $$
        DECLARE
            v_user_id UUID;
        BEGIN
            INSERT INTO tb_user (username, email, password_hash)
            VALUES (p_username, p_email, p_password_hash)
            RETURNING id INTO v_user_id;

            RETURN (SELECT data FROM v_user WHERE id = v_user_id);
        END;
        $$ LANGUAGE plpgsql;
    """)
    yield db
    db.teardown()


def test_compile_schema_against_real_database(test_db):
    """Test compiling schema against real PostgreSQL database."""
    schema_source = '''
import FraiseQL

@FraiseQL.type
class User:
    id: UUID  # UUID v4 for GraphQL ID
    username: str
    email: str
    created_at: str
    updated_at: str

@FraiseQL.query
def user(id: str) -> User:
    pass

@FraiseQL.query
def users() -> list[User]:
    pass

@FraiseQL.input
class CreateUserInput:
    username: str
    email: str
    password: str

@FraiseQL.mutation
def create_user(input: CreateUserInput) -> User:
    pass

@FraiseQL.binding("user", view="v_user", where_column="id")
@FraiseQL.binding("users", view="v_user")
@FraiseQL.binding("create_user", procedure="fn_create_user",
                  input_mapping={"password": "password_hash"})
class Bindings:
    pass
    '''

    compiled = compile_schema(
        source=schema_source,
        language="python",
        database=test_db.connection,
        target="postgresql"
    )

    # Verify compilation succeeded
    assert compiled.version == "1.0"
    assert "User" in compiled.types
    assert "user" in compiled.queries
    assert "users" in compiled.queries
    assert "create_user" in compiled.mutations

    # Verify WHERE types generated from actual database columns
    assert "UserWhereInput" in compiled.types
    user_where = compiled.types["UserWhereInput"]
    assert "username" in user_where.fields
    assert "email" in user_where.fields

    # Check operators match database capabilities
    username_field = user_where.fields["username"]
    assert "eq" in username_field.operators
    assert "like" in username_field.operators
    assert "in" in username_field.operators

    # Verify procedure binding
    create_mutation = compiled.mutations["create_user"]
    assert create_mutation.binding.procedure_name == "fn_create_user"
    assert create_mutation.binding.input_mapping["password"] == "password_hash"

    # Save compiled schema
    compiled.save("test_schema.json")


def test_compile_schema_with_missing_view(test_db):
    """Test compilation fails gracefully when view doesn't exist."""
    schema_source = '''
import FraiseQL

@FraiseQL.type
class Product:
    id: UUID  # UUID v4 for GraphQL ID
    name: str

@FraiseQL.query
def products() -> list[Product]:
    pass

@FraiseQL.binding("products", view="v_product_missing")
class Bindings:
    pass
    '''

    with pytest.raises(CompilationError) as exc_info:
        compile_schema(
            source=schema_source,
            language="python",
            database=test_db.connection,
            target="postgresql"
        )

    assert exc_info.value.code == "E_BINDING_VIEW_NOT_FOUND_010"
    assert "v_product_missing" in str(exc_info.value)

    # Error should suggest available views
    assert "v_user" in str(exc_info.value)
```text
<!-- Code example in TEXT -->

### 2.2 Runtime Integration Tests

**What to test:** Runtime executing queries against real database

**Directory:** `tests/integration/runtime/`

#### 2.2.1 Query Execution Tests

```rust
<!-- Code example in RUST -->
// tests/integration/runtime/test_query_execution.rs
use fraiseql_runtime::Runtime;
use fraiseql_testing::{TestDatabase, load_compiled_schema};

#[tokio::test]
async fn test_execute_simple_query() {
    let db = TestDatabase::new().await;
    db.seed_data("fixtures/users.sql").await;

    let schema = load_compiled_schema("test_schema.json");
    let runtime = Runtime::new(schema, db.pool()).await.unwrap();

    let query = r#"
        query {
            user(id: "user-123") {
                id
                username
                email
            }
        }
    "#;

    let result = runtime.execute(query, None, None).await.unwrap();

    assert!(result.errors.is_none());
    assert_eq!(result.data["user"]["id"], "user-123");
    assert_eq!(result.data["user"]["username"], "alice");
    assert_eq!(result.data["user"]["email"], "alice@example.com");
}

#[tokio::test]
async fn test_execute_query_with_where_filter() {
    let db = TestDatabase::new().await;
    db.seed_data("fixtures/users.sql").await;

    let schema = load_compiled_schema("test_schema.json");
    let runtime = Runtime::new(schema, db.pool()).await.unwrap();

    let query = r#"
        query {
            users(where: { username: { like: "alice%" } }) {
                id
                username
            }
        }
    "#;

    let result = runtime.execute(query, None, None).await.unwrap();

    assert!(result.errors.is_none());
    assert!(result.data["users"].as_array().unwrap().len() > 0);
    assert!(result.data["users"][0]["username"].as_str().unwrap().starts_with("alice"));
}

#[tokio::test]
async fn test_execute_query_with_variables() {
    let db = TestDatabase::new().await;
    db.seed_data("fixtures/users.sql").await;

    let schema = load_compiled_schema("test_schema.json");
    let runtime = Runtime::new(schema, db.pool()).await.unwrap();

    let query = r#"
        query GetUser($userId: ID!) {
            user(id: $userId) {
                id
                username
            }
        }
    "#;

    let variables = serde_json::json!({
        "userId": "user-123"
    });

    let result = runtime.execute(query, Some(variables), None).await.unwrap();

    assert!(result.errors.is_none());
    assert_eq!(result.data["user"]["id"], "user-123");
}

#[tokio::test]
async fn test_execute_query_with_authorization() {
    let db = TestDatabase::new().await;
    db.seed_data("fixtures/users.sql").await;

    let schema = load_compiled_schema("schema_with_auth.json");
    let runtime = Runtime::new(schema, db.pool()).await.unwrap();

    let query = r#"
        query {
            adminUsers {
                id
                username
            }
        }
    "#;

    // Without auth context (should fail)
    let result = runtime.execute(query, None, None).await.unwrap();
    assert!(result.errors.is_some());
    assert_eq!(result.errors.unwrap()[0].code, "E_RUNTIME_AUTH_UNAUTHENTICATED_200");

    // With non-admin user (should fail)
    let user_auth = AuthContext {
        user_id: Some("user-456".to_string()),
        roles: vec!["user".to_string()],
        authenticated: true,
        ..Default::default()
    };
    let result = runtime.execute(query, None, Some(user_auth)).await.unwrap();
    assert!(result.errors.is_some());
    assert_eq!(result.errors.unwrap()[0].code, "E_RUNTIME_AUTH_FORBIDDEN_201");

    // With admin user (should succeed)
    let admin_auth = AuthContext {
        user_id: Some("user-123".to_string()),
        roles: vec!["admin".to_string()],
        authenticated: true,
        ..Default::default()
    };
    let result = runtime.execute(query, None, Some(admin_auth)).await.unwrap();
    assert!(result.errors.is_none());
}
```text
<!-- Code example in TEXT -->

#### 2.2.2 Mutation Execution Tests

```rust
<!-- Code example in RUST -->
// tests/integration/runtime/test_mutation_execution.rs
use fraiseql_runtime::Runtime;
use fraiseql_testing::{TestDatabase, load_compiled_schema};

#[tokio::test]
async fn test_execute_create_mutation() {
    let db = TestDatabase::new().await;

    let schema = load_compiled_schema("test_schema.json");
    let runtime = Runtime::new(schema, db.pool()).await.unwrap();

    let mutation = r#"
        mutation {
            createUser(input: {
                username: "bob",
                email: "bob@example.com",
                password: "secret123"
            }) {
                id
                username
                email
            }
        }
    "#;

    let result = runtime.execute(mutation, None, None).await.unwrap();

    assert!(result.errors.is_none());
    assert!(result.data["createUser"]["id"].is_string());
    assert_eq!(result.data["createUser"]["username"], "bob");
    assert_eq!(result.data["createUser"]["email"], "bob@example.com");

    // Verify data was actually inserted
    let verify_query = r#"
        query {
            users(where: { username: { eq: "bob" } }) {
                username
            }
        }
    "#;
    let verify_result = runtime.execute(verify_query, None, None).await.unwrap();
    assert_eq!(verify_result.data["users"][0]["username"], "bob");
}

#[tokio::test]
async fn test_execute_update_mutation() {
    let db = TestDatabase::new().await;
    db.seed_data("fixtures/users.sql").await;

    let schema = load_compiled_schema("test_schema.json");
    let runtime = Runtime::new(schema, db.pool()).await.unwrap();

    let mutation = r#"
        mutation {
            updateUser(
                id: "user-123",
                input: { email: "newemail@example.com" }
            ) {
                id
                email
            }
        }
    "#;

    let result = runtime.execute(mutation, None, None).await.unwrap();

    assert!(result.errors.is_none());
    assert_eq!(result.data["updateUser"]["email"], "newemail@example.com");
}

#[tokio::test]
async fn test_mutation_rollback_on_error() {
    let db = TestDatabase::new().await;
    db.seed_data("fixtures/users.sql").await;

    let schema = load_compiled_schema("test_schema.json");
    let runtime = Runtime::new(schema, db.pool()).await.unwrap();

    let mutation = r#"
        mutation {
            createUser(input: {
                username: "alice",  # Duplicate username (constraint violation)
                email: "alice2@example.com",
                password: "secret"
            }) {
                id
                username
            }
        }
    "#;

    let result = runtime.execute(mutation, None, None).await.unwrap();

    // Should return error
    assert!(result.errors.is_some());
    assert_eq!(result.errors.unwrap()[0].code, "E_RUNTIME_DATABASE_CONSTRAINT_300");

    // Verify no data was inserted (transaction rolled back)
    let verify_query = r#"
        query {
            users(where: { email: { eq: "alice2@example.com" } }) {
                email
            }
        }
    "#;
    let verify_result = runtime.execute(verify_query, None, None).await.unwrap();
    assert_eq!(verify_result.data["users"].as_array().unwrap().len(), 0);
}
```text
<!-- Code example in TEXT -->

### 2.3 Database Integration Tests

**What to test:** Database views, procedures, and conventions

**Directory:** `tests/integration/database/`

#### 2.3.1 View Tests

```python
<!-- Code example in Python -->
# tests/integration/database/test_views.py
import pytest
from FraiseQL.testing import DatabaseFixture

@pytest.fixture
def db():
    db = DatabaseFixture()
    db.execute_sql("""
        CREATE TABLE tb_user (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username TEXT NOT NULL,
            email TEXT NOT NULL
        );

        CREATE TABLE tb_post (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES tb_user(id),
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    yield db
    db.teardown()


def test_v_user_view_structure(db):
    """Test v_user view produces correct structure."""
    # Insert test data
    db.execute_sql("""
        INSERT INTO tb_user (id, username, email)
        VALUES ('00000000-0000-0000-0000-000000000001', 'alice', 'alice@example.com');
    """)

    # Create view
    db.execute_sql("""
        CREATE VIEW v_user AS
        SELECT
            id,
            jsonb_build_object(
                'id', id::text,
                'username', username,
                'email', email
            ) AS data
        FROM tb_user;
    """)

    # Query view
    result = db.query_one("SELECT * FROM v_user WHERE id = '00000000-0000-0000-0000-000000000001'")

    assert result["id"] is not None
    assert result["data"] is not None
    assert result["data"]["id"] == "00000000-0000-0000-0000-000000000001"
    assert result["data"]["username"] == "alice"
    assert result["data"]["email"] == "alice@example.com"


def test_v_posts_by_user_aggregation(db):
    """Test pre-aggregated view for nested data."""
    # Insert test data
    db.execute_sql("""
        INSERT INTO tb_user (id, username, email)
        VALUES ('00000000-0000-0000-0000-000000000001', 'alice', 'alice@example.com');

        INSERT INTO tb_post (id, user_id, title, content)
        VALUES
            ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'First post', 'Content 1'),
            ('10000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'Second post', 'Content 2');
    """)

    # Create aggregated view
    db.execute_sql("""
        CREATE VIEW v_posts_by_user AS
        SELECT
            user_id,
            jsonb_agg(
                jsonb_build_object(
                    'id', id::text,
                    'title', title,
                    'content', content,
                    'createdAt', created_at
                )
                ORDER BY created_at DESC
            ) AS data
        FROM tb_post
        GROUP BY user_id;
    """)

    # Query aggregated view
    result = db.query_one("SELECT * FROM v_posts_by_user WHERE user_id = '00000000-0000-0000-0000-000000000001'")

    assert result["data"] is not None
    assert len(result["data"]) == 2
    assert result["data"][0]["title"] == "Second post"  # Ordered by created_at DESC
    assert result["data"][1]["title"] == "First post"
```text
<!-- Code example in TEXT -->

#### 2.3.2 Stored Procedure Tests

```python
<!-- Code example in Python -->
# tests/integration/database/test_procedures.py
import pytest
from FraiseQL.testing import DatabaseFixture

def test_fn_create_user_procedure(db):
    """Test stored procedure returns correct JSONB structure."""
    db.execute_sql("""
        CREATE TABLE tb_user (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username TEXT NOT NULL,
            email TEXT NOT NULL,
            password_hash TEXT NOT NULL
        );

        CREATE VIEW v_user AS
        SELECT
            id,
            jsonb_build_object(
                'id', id::text,
                'username', username,
                'email', email
            ) AS data
        FROM tb_user;

        CREATE FUNCTION fn_create_user(
            p_username TEXT,
            p_email TEXT,
            p_password_hash TEXT
        ) RETURNS JSONB AS $$
        DECLARE
            v_user_id UUID;
        BEGIN
            INSERT INTO tb_user (username, email, password_hash)
            VALUES (p_username, p_email, p_password_hash)
            RETURNING id INTO v_user_id;

            RETURN (SELECT data FROM v_user WHERE id = v_user_id);
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Call procedure
    result = db.query_one("""
        SELECT fn_create_user('alice', 'alice@example.com', 'hash123') AS result
    """)

    assert result["result"] is not None
    assert result["result"]["username"] == "alice"
    assert result["result"]["email"] == "alice@example.com"
    assert "password_hash" not in result["result"]  # Excluded from projection


def test_fn_update_user_procedure_with_optimistic_locking(db):
    """Test update procedure with version-based optimistic locking."""
    db.execute_sql("""
        CREATE TABLE tb_user (
            id UUID PRIMARY KEY,
            username TEXT NOT NULL,
            version INT NOT NULL DEFAULT 1
        );

        INSERT INTO tb_user (id, username) VALUES ('00000000-0000-0000-0000-000000000001', 'alice');

        CREATE FUNCTION fn_update_user(
            p_id UUID,
            p_username TEXT,
            p_expected_version INT
        ) RETURNS JSONB AS $$
        DECLARE
            v_updated_rows INT;
        BEGIN
            UPDATE tb_user
            SET username = p_username, version = version + 1
            WHERE id = p_id AND version = p_expected_version;

            GET DIAGNOSTICS v_updated_rows = ROW_COUNT;

            IF v_updated_rows = 0 THEN
                RAISE EXCEPTION 'optimistic_lock_failed';
            END IF;

            RETURN jsonb_build_object('success', true);
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Successful update (correct version)
    result = db.query_one("SELECT fn_update_user('00000000-0000-0000-0000-000000000001', 'alice2', 1) AS result")
    assert result["result"]["success"] is True

    # Failed update (stale version)
    with pytest.raises(Exception) as exc_info:
        db.query_one("SELECT fn_update_user('00000000-0000-0000-0000-000000000001', 'alice3', 1) AS result")

    assert "optimistic_lock_failed" in str(exc_info.value)
```text
<!-- Code example in TEXT -->

---

## 3. End-to-End (E2E) Testing Strategy

### 3.1 Client Workflow Tests

**What to test:** Complete user workflows from client perspective

**Directory:** `tests/e2e/`

#### 3.1.1 E2E Query Tests

```typescript
<!-- Code example in TypeScript -->
// tests/e2e/test_user_workflows.ts
import { FraiseQLClient } from '@FraiseQL/client';
import { describe, it, expect, beforeAll, afterAll } from '@jest/globals';

describe('User Workflows', () => {
  let client: FraiseQLClient;

  beforeAll(async () => {
    client = new FraiseQLClient({
      endpoint: 'http://localhost:8080/graphql',
    });
  });

  it('should fetch user by ID', async () => {
    const query = `
      query GetUser($userId: ID!) {
        user(id: $userId) {
          id
          username
          email
        }
      }
    `;

    const result = await client.query(query, { userId: 'user-123' });

    expect(result.errors).toBeUndefined();
    expect(result.data.user.id).toBe('user-123');
    expect(result.data.user.username).toBeTruthy();
  });

  it('should list users with filtering', async () => {
    const query = `
      query ListUsers {
        users(where: { username: { like: "alice%" } }) {
          id
          username
        }
      }
    `;

    const result = await client.query(query);

    expect(result.errors).toBeUndefined();
    expect(result.data.users).toBeInstanceOf(Array);
    expect(result.data.users.length).toBeGreaterThan(0);
    expect(result.data.users[0].username).toMatch(/^alice/);
  });

  it('should fetch user with nested posts', async () => {
    const query = `
      query GetUserWithPosts($userId: ID!) {
        user(id: $userId) {
          id
          username
          posts {
            id
            title
            createdAt
          }
        }
      }
    `;

    const result = await client.query(query, { userId: 'user-123' });

    expect(result.errors).toBeUndefined();
    expect(result.data.user.posts).toBeInstanceOf(Array);
  });
});

describe('Mutation Workflows', () => {
  let client: FraiseQLClient;

  beforeAll(async () => {
    client = new FraiseQLClient({
      endpoint: 'http://localhost:8080/graphql',
    });
  });

  it('should create user, fetch, update, delete (CRUD workflow)', async () => {
    // CREATE
    const createMutation = `
      mutation CreateUser($input: CreateUserInput!) {
        createUser(input: $input) {
          id
          username
          email
        }
      }
    `;

    const createResult = await client.mutate(createMutation, {
      input: {
        username: 'testuser',
        email: 'test@example.com',
        password: 'secret123'
      }
    });

    expect(createResult.errors).toBeUndefined();
    const userId = createResult.data.createUser.id;
    expect(userId).toBeTruthy();

    // READ
    const readQuery = `
      query GetUser($id: ID!) {
        user(id: $id) {
          id
          username
          email
        }
      }
    `;

    const readResult = await client.query(readQuery, { id: userId });
    expect(readResult.data.user.username).toBe('testuser');

    // UPDATE
    const updateMutation = `
      mutation UpdateUser($id: ID!, $input: UpdateUserInput!) {
        updateUser(id: $id, input: $input) {
          id
          email
        }
      }
    `;

    const updateResult = await client.mutate(updateMutation, {
      id: userId,
      input: { email: 'newemail@example.com' }
    });

    expect(updateResult.data.updateUser.email).toBe('newemail@example.com');

    // DELETE
    const deleteMutation = `
      mutation DeleteUser($id: ID!) {
        deleteUser(id: $id) {
          success
        }
      }
    `;

    const deleteResult = await client.mutate(deleteMutation, { id: userId });
    expect(deleteResult.data.deleteUser.success).toBe(true);

    // Verify deleted
    const verifyResult = await client.query(readQuery, { id: userId });
    expect(verifyResult.data.user).toBeNull();
  });
});

describe('Authorization Workflows', () => {
  it('should reject unauthenticated request', async () => {
    const client = new FraiseQLClient({
      endpoint: 'http://localhost:8080/graphql',
      // No auth token
    });

    const query = `
      query {
        adminUsers {
          id
          username
        }
      }
    `;

    const result = await client.query(query);

    expect(result.errors).toBeDefined();
    expect(result.errors[0].code).toBe('E_RUNTIME_AUTH_UNAUTHENTICATED_200');
  });

  it('should allow authenticated admin request', async () => {
    const adminClient = new FraiseQLClient({
      endpoint: 'http://localhost:8080/graphql',
      headers: {
        Authorization: 'Bearer admin-token-123'
      }
    });

    const query = `
      query {
        adminUsers {
          id
          username
        }
      }
    `;

    const result = await adminClient.query(query);

    expect(result.errors).toBeUndefined();
    expect(result.data.adminUsers).toBeInstanceOf(Array);
  });
});
```text
<!-- Code example in TEXT -->

### 3.2 Performance Tests

**What to test:** Latency, throughput, resource usage

**Directory:** `tests/e2e/performance/`

#### 3.2.1 Query Latency Tests

```typescript
<!-- Code example in TypeScript -->
// tests/e2e/performance/test_latency.ts
import { FraiseQLClient } from '@FraiseQL/client';

describe('Query Latency', () => {
  it('should complete simple query in <50ms (p50)', async () => {
    const client = new FraiseQLClient({ endpoint: 'http://localhost:8080/graphql' });
    const query = `query { user(id: "user-123") { id username } }`;

    const latencies: number[] = [];

    for (let i = 0; i < 100; i++) {
      const start = Date.now();
      await client.query(query);
      const duration = Date.now() - start;
      latencies.push(duration);
    }

    latencies.sort((a, b) => a - b);
    const p50 = latencies[49];
    const p95 = latencies[94];
    const p99 = latencies[98];

    console.log(`Latency: p50=${p50}ms, p95=${p95}ms, p99=${p99}ms`);

    expect(p50).toBeLessThan(50);
    expect(p95).toBeLessThan(200);
    expect(p99).toBeLessThan(500);
  });

  it('should complete nested query in <200ms (p95)', async () => {
    const client = new FraiseQLClient({ endpoint: 'http://localhost:8080/graphql' });
    const query = `
      query {
        user(id: "user-123") {
          id
          username
          posts {
            id
            title
            comments {
              id
              content
            }
          }
        }
      }
    `;

    const latencies: number[] = [];

    for (let i = 0; i < 100; i++) {
      const start = Date.now();
      await client.query(query);
      const duration = Date.now() - start;
      latencies.push(duration);
    }

    latencies.sort((a, b) => a - b);
    const p95 = latencies[94];

    expect(p95).toBeLessThan(200);
  });
});
```text
<!-- Code example in TEXT -->

#### 3.2.2 Throughput Tests

```typescript
<!-- Code example in TypeScript -->
// tests/e2e/performance/test_throughput.ts
import { FraiseQLClient } from '@FraiseQL/client';

describe('Query Throughput', () => {
  it('should handle 10,000+ queries/second', async () => {
    const client = new FraiseQLClient({ endpoint: 'http://localhost:8080/graphql' });
    const query = `query { users { id username } }`;

    const duration = 10_000; // 10 seconds
    const start = Date.now();
    let queryCount = 0;

    // Parallel execution (100 concurrent clients)
    const clients = Array(100).fill(null).map(() =>
      (async () => {
        while (Date.now() - start < duration) {
          await client.query(query);
          queryCount++;
        }
      })()
    );

    await Promise.all(clients);

    const elapsed = (Date.now() - start) / 1000;
    const qps = queryCount / elapsed;

    console.log(`Throughput: ${qps.toFixed(0)} queries/second`);

    expect(qps).toBeGreaterThan(10_000);
  });
});
```text
<!-- Code example in TEXT -->

---

## 4. Test Data Management

### 4.1 Fixtures

**Location:** `tests/fixtures/`

#### 4.1.1 SQL Fixtures

```sql
<!-- Code example in SQL -->
-- tests/fixtures/users.sql
INSERT INTO tb_user (id, username, email, password_hash) VALUES
  ('00000000-0000-0000-0000-000000000001', 'alice', 'alice@example.com', 'hash1'),
  ('00000000-0000-0000-0000-000000000002', 'bob', 'bob@example.com', 'hash2'),
  ('00000000-0000-0000-0000-000000000003', 'charlie', 'charlie@example.com', 'hash3');

INSERT INTO tb_post (id, user_id, title, content) VALUES
  ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'Alice Post 1', 'Content'),
  ('10000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'Alice Post 2', 'Content'),
  ('10000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000002', 'Bob Post 1', 'Content');
```text
<!-- Code example in TEXT -->

#### 4.1.2 Compiled Schema Fixtures

```json
<!-- Code example in JSON -->
// tests/fixtures/simple_schema.json
{
  "version": "1.0",
  "metadata": {
    "name": "test-schema",
    "databaseTarget": "postgresql"
  },
  "types": [
    {
      "name": "User",
      "kind": "object",
      "fields": [
        { "name": "id", "type": "ID!" },
        { "name": "username", "type": "String!" },
        { "name": "email", "type": "String!" }
      ]
    }
  ],
  "queries": [
    {
      "name": "user",
      "arguments": [{ "name": "id", "type": "ID!" }],
      "returnType": "User"
    }
  ],
  "bindings": {
    "user": {
      "view_name": "v_user",
      "where_column": "id"
    }
  }
}
```text
<!-- Code example in TEXT -->

### 4.2 Test Database Management

```python
<!-- Code example in Python -->
# tests/utils/database.py
import psycopg
from contextlib import contextmanager

class DatabaseFixture:
    """Test database fixture with automatic setup/teardown."""

    def __init__(self, database_name="fraiseql_test"):
        self.database_name = database_name
        self.connection = self._create_test_database()

    def _create_test_database(self):
        """Create test database and return connection."""
        # Connect to postgres database
        with psycopg.connect("dbname=postgres") as conn:
            conn.autocommit = True
            conn.execute(f"DROP DATABASE IF EXISTS {self.database_name}")
            conn.execute(f"CREATE DATABASE {self.database_name}")

        # Connect to test database
        return psycopg.connect(f"dbname={self.database_name}")

    def execute_sql(self, sql: str):
        """Execute SQL statement."""
        with self.connection.cursor() as cur:
            cur.execute(sql)
        self.connection.commit()

    def query_one(self, sql: str):
        """Execute query and return single row."""
        with self.connection.cursor() as cur:
            cur.execute(sql)
            return cur.fetchone()

    def seed_data(self, fixture_path: str):
        """Load SQL fixture file."""
        with open(fixture_path) as f:
            self.execute_sql(f.read())

    def teardown(self):
        """Clean up test database."""
        self.connection.close()
        with psycopg.connect("dbname=postgres") as conn:
            conn.autocommit = True
            conn.execute(f"DROP DATABASE IF EXISTS {self.database_name}")
```text
<!-- Code example in TEXT -->

---

## 5. CI/CD Testing Pipeline

### 5.1 GitHub Actions Workflow

```yaml
<!-- Code example in YAML -->
# .github/workflows/test.yml
name: Test Suite

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  unit-tests-compiler:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install uv
          uv pip install -e ".[dev]"

      - name: Run compiler unit tests
        run: |
          pytest tests/unit/compiler/ -v --cov=FraiseQL.compiler --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          files: ./coverage.xml
          flags: compiler

  unit-tests-runtime:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Rust
        uses: actions-rs/toolchain@v1
        with:
          toolchain: stable

      - name: Run runtime unit tests
        run: |
          cargo test --lib --bins

      - name: Generate coverage
        run: |
          cargo tarpaulin --out Xml

      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          files: ./cobertura.xml
          flags: runtime

  integration-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install uv
          uv pip install -e ".[dev]"

      - name: Run integration tests
        env:
          DATABASE_URL: postgresql://postgres:postgres@localhost:5432/postgres
        run: |
          pytest tests/integration/ -v --cov --cov-report=xml

  e2e-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v3

      - name: Build runtime
        run: |
          cargo build --release

      - name: Start FraiseQL server
        run: |
          ./target/release/FraiseQL-server \
            --schema tests/fixtures/e2e_schema.json \
            --database postgresql://postgres:postgres@localhost:5432/postgres &
          sleep 5

      - name: Run E2E tests
        run: |
          npm install
          npm run test:e2e

  performance-tests:
    runs-on: ubuntu-latest
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v3

      - name: Run performance benchmarks
        run: |
          cargo build --release
          ./target/release/FraiseQL-bench

      - name: Upload benchmark results
        uses: benchmark-action/github-action-benchmark@v1
        with:
          tool: 'cargo'
          output-file-path: benchmark_results.json
```text
<!-- Code example in TEXT -->

### 5.2 Test Coverage Requirements

```toml
<!-- Code example in TOML -->
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
python_classes = "Test*"
python_functions = "test_*"

# Coverage thresholds
fail_under = 95  # Fail if coverage < 95%

[tool.coverage.run]
branch = true
source = ["FraiseQL"]

[tool.coverage.report]
precision = 2
show_missing = true
skip_covered = false
```text
<!-- Code example in TEXT -->

```toml
<!-- Code example in TOML -->
# Cargo.toml
[dev-dependencies]
criterion = "0.5"
proptest = "1.0"

[[bench]]
name = "query_execution"
harness = false
```text
<!-- Code example in TEXT -->

---

## 6. Testing Best Practices

### 6.1 Test Organization

```text
<!-- Code example in TEXT -->
tests/
├── unit/                   # Fast, isolated tests
│   ├── compiler/
│   │   ├── test_parsing.py
│   │   ├── test_binding.py
│   │   └── test_validation.py
│   └── runtime/
│       ├── test_query_parsing.rs
│       ├── test_authorization.rs
│       └── test_projection.rs
│
├── integration/            # Database-dependent tests
│   ├── compiler/
│   │   └── test_compilation_e2e.py
│   ├── runtime/
│   │   ├── test_query_execution.rs
│   │   └── test_mutation_execution.rs
│   └── database/
│       ├── test_views.py
│       └── test_procedures.py
│
├── e2e/                    # Full workflow tests
│   ├── test_user_workflows.ts
│   ├── test_authorization.ts
│   └── performance/
│       ├── test_latency.ts
│       └── test_throughput.ts
│
├── fixtures/               # Test data
│   ├── users.sql
│   ├── posts.sql
│   └── simple_schema.json
│
└── utils/                  # Test utilities
    ├── database.py
    └── client.ts
```text
<!-- Code example in TEXT -->

### 6.2 Naming Conventions

```python
<!-- Code example in Python -->
# Good test names (describe what, when, and expected)
def test_parse_simple_type():
    """Test parsing a simple @FraiseQL.type decorated class."""

def test_bind_type_missing_view():
    """Test binding fails when view doesn't exist."""

def test_execute_query_with_authorization():
    """Test query execution enforces authorization rules."""

# Bad test names (vague, unclear expectations)
def test_parser():           # What about parser?
def test_binding_error():    # Which error?
def test_query():            # Test what about query?
```text
<!-- Code example in TEXT -->

### 6.3 Test Independence

```python
<!-- Code example in Python -->
# Good: Each test is independent
def test_create_user(db):
    user_id = create_user(db, "alice")
    assert user_id is not None

def test_update_user(db):
    user_id = create_user(db, "bob")  # Create own data
    update_user(db, user_id, email="newemail@example.com")
    user = get_user(db, user_id)
    assert user.email == "newemail@example.com"

# Bad: Tests depend on each other
user_id = None

def test_create_user(db):
    global user_id
    user_id = create_user(db, "alice")
    assert user_id is not None

def test_update_user(db):
    global user_id
    update_user(db, user_id, email="newemail@example.com")  # Depends on previous test
```text
<!-- Code example in TEXT -->

### 6.4 Deterministic Tests

```python
<!-- Code example in Python -->
# Good: Deterministic (always same result)
def test_query_users_by_username():
    db.seed_fixture("users.sql")  # Known data
    users = query_users(where={"username": {"eq": "alice"}})
    assert len(users) == 1
    assert users[0].username == "alice"

# Bad: Non-deterministic (depends on current time)
def test_query_recent_users():
    users = query_users(where={"created_at": {"gt": "now() - interval '1 day'"}})
    assert len(users) > 0  # May fail if no recent users
```text
<!-- Code example in TEXT -->

### 6.5 Test Documentation

```python
<!-- Code example in Python -->
def test_compile_schema_with_nested_types(db):
    """
    Test compiling schema with nested types (User.posts).

    Scenario:
        - User type has posts field of type [Post!]!
        - Post type has user field of type User!
        - Circular reference should compile without error

    Expected:
        - Compilation succeeds
        - Both types are in compiled schema
        - Nested field bindings are correct

    Regression:
        Fixes bug where circular references caused infinite loop (Issue #123)
    """
    schema_source = '''...'''
    compiled = compile_schema(source=schema_source, database=db)
    # ... assertions ...
```text
<!-- Code example in TEXT -->

---

## 7. Continuous Testing

### 7.1 Pre-commit Hooks

```yaml
<!-- Code example in YAML -->
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: pytest-quick
        name: Run quick unit tests
        entry: pytest tests/unit/ -x --tb=short
        language: system
        pass_filenames: false
        always_run: true

      - id: cargo-test
        name: Run Rust unit tests
        entry: cargo test --lib
        language: system
        pass_filenames: false
        always_run: true
```text
<!-- Code example in TEXT -->

### 7.2 Watch Mode (Development)

```bash
<!-- Code example in BASH -->
# Python: Auto-run tests on file change
$ ptw tests/unit/compiler/ --runner "pytest -x"

# Rust: Auto-run tests on file change
$ cargo watch -x test
```text
<!-- Code example in TEXT -->

---

## Summary

FraiseQL's testing strategy is **comprehensive, deterministic, and fast**:

- **95%+ coverage** across compiler, runtime, and database layers
- **Layered testing** (unit → integration → E2E)
- **Fast feedback** (unit tests <1s, integration <30s, E2E <5min)
- **Zero flaky tests** (deterministic execution = deterministic tests)
- **Continuous testing** (CI/CD pipeline + pre-commit hooks)

**Test pyramid distribution:**

- 60% unit tests (1000-2000 tests) — Fast, isolated
- 30% integration tests (500-800 tests) — Database-dependent
- 10% E2E tests (100-200 tests) — Full workflows

**Every bug gets a regression test before fix.** This ensures FraiseQL remains stable and reliable as it evolves.

---

**Status: COMPLETE** ✅

All testing strategies documented and ready for implementation.

---

## Troubleshooting

### "Test database connection fails: 'Connection refused'"

**Cause:** PostgreSQL container not started or port not accessible.

**Diagnosis:**

1. Check if container is running: `docker ps | grep postgres`
2. Verify port is listening: `netstat -tuln | grep 5432`
3. Test connectivity: `psql postgresql://user:pass@localhost:5432/test_db`

**Solutions:**

- Start database: `docker-compose up -d` in test directory
- Verify DATABASE_URL is correct
- Check firewall rules allowing localhost:5432
- Wait for database startup (may take 10-20 seconds)

### "Flaky tests that pass sometimes, fail other times"

**Cause:** Race conditions in database state or test isolation issues.

**Diagnosis:**

1. Run failing test 10 times: `cargo test test_name -- --test-threads=1 --nocapture`
2. Look for non-deterministic behavior (random data, timestamps)
3. Check test fixture cleanup: does previous test affect next test?

**Solutions:**

- Use test fixtures with unique IDs per test (UUIDs)
- Add test isolation: truncate tables before each test
- Avoid real time dependencies: use mock time or fixed dates
- Run tests sequentially: `cargo test -- --test-threads=1` (slower but more reliable)
- Use database transactions that rollback after each test

### "E2E test hangs waiting for response"

**Cause:** Server not responding or database query blocking.

**Diagnosis:**

1. Check if FraiseQL server is running: `curl http://localhost:8000/health`
2. Check database: `docker exec postgres psql -U test -d test_db -c 'SELECT 1;'`
3. Look for slow query: enable query logging in database

**Solutions:**

- Increase test timeout: `#[tokio::test(timeout = 60000ms)]`
- Verify database has test data loaded
- Check for deadlocks: `SELECT * FROM pg_locks;`
- Simplify query to identify bottleneck
- Ensure indexes exist on frequently queried columns

### "Test coverage report shows <90% coverage"

**Cause:** Some code paths not exercised by tests.

**Diagnosis:**

1. Generate coverage report: `cargo tarpaulin --out Html`
2. Open `tarpaulin-report.html` and find uncovered lines
3. Identify if untested code is: error paths, edge cases, or dead code

**Solutions:**

- Add error case tests: test both happy path and all error conditions
- Add edge case tests: empty lists, NULL values, boundary conditions
- For unreachable code: either delete it or mark `#[allow(dead_code)]` with comment
- Ensure all error branches have tests

### "Integration test fails with 'Foreign key constraint violation'"

**Cause:** Test inserts data in wrong order or doesn't respect dependencies.

**Diagnosis:**

1. Check test fixture order: which table is inserted first?
2. Verify foreign key relationships: `SELECT constraint_name FROM information_schema.key_column_usage;`
3. Look at error - it will show which FK constraint failed

**Solutions:**

- Insert parent records before children
- Use fixtures that auto-setup dependencies
- Disable FK checks during setup if safe: `SET CONSTRAINTS ALL DEFERRED;`
- Clean up in reverse order (children before parents)

### "Test database grows too large (test_db.db > 1GB)"

**Cause:** Test data not cleaned up between test runs or transaction not rolling back.

**Diagnosis:**

1. Check file size: `du -h test_db.db`
2. List tables: `SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(...)) FROM pg_tables;`
3. Find bloated table: `SELECT * FROM pg_stat_user_tables ORDER BY n_live_tup DESC;`

**Solutions:**

- Clean up database between test suites: truncate all tables
- Use `TRUNCATE TABLE ... CASCADE;` to reset identity columns
- Use transaction rollback instead of delete (faster cleanup)
- For SQLite: use `VACUUM;` to reclaim space
- Reduce test data size (generate minimal records)

### "Test compilation slow (>5 minutes)"

**Cause:** Large number of tests or heavy dependencies.

**Diagnosis:**

1. Check test count: `cargo test --lib -- --list | wc -l`
2. Profile compilation: `cargo build -p FraiseQL-core --release --timings`
3. Look for slow dependencies in output

**Solutions:**

- Use `cargo nextest` for faster test execution (2-3x speedup)
- Compile tests in release mode for CI (slower compile, faster tests)
- Split tests into multiple binaries (compile in parallel)
- Use `#[cfg(test)] mod test_helpers;` to avoid recompiling test code

### "Test requires fresh database state but previous test left data"

**Cause:** Lack of test isolation - tests run in same transaction or database.

**Diagnosis:**

1. Run tests in different order: `cargo test -- --test-threads=1`
2. Check if ordering affects results
3. Look for hardcoded IDs in tests (sign of shared state)

**Solutions:**

- Use `#[test]` with explicit setup/teardown for each test
- Create unique data per test (use test name or counter)
- Use `tokio::test` with database transactions that rollback
- Ensure CI drops and recreates test database before each run

---

## See Also

- **[Developer Guide](./development/developer-guide.md)** - Development setup and workflow
- **[CI/CD Integration](../ci-cd-integration.md)** - Continuous integration and automated testing

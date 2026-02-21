//! Benchmarks for mutation pipeline performance

use criterion::{Criterion, black_box, criterion_group, criterion_main};
use fraiseql_rs::mutation::build_mutation_response;

fn benchmark_simple_format(c: &mut Criterion) {
    let json = r#"{"id": "123", "first_name": "John", "last_name": "Doe"}"#;

    c.bench_function("simple_format", |b| {
        b.iter(|| {
            build_mutation_response(
                black_box(json),
                "createUser",
                "CreateUserSuccess",
                "CreateUserError",
                Some("user"),
                Some("User"),
                None,
                true,
                None,
                None,
            )
        })
    });
}

fn benchmark_full_format_with_cascade(c: &mut Criterion) {
    let json = r#"{
        "status": "created",
        "message": "User created",
        "entity_type": "User",
        "entity": {"id": "123", "first_name": "John", "last_name": "Doe"},
        "cascade": {
            "updated": [{"id": "user-123", "post_count": 5}],
            "deleted": [],
            "invalidations": ["User:123"]
        }
    }"#;

    c.bench_function("full_format_cascade", |b| {
        b.iter(|| {
            build_mutation_response(
                black_box(json),
                "createUser",
                "CreateUserSuccess",
                "CreateUserError",
                Some("user"),
                Some("User"),
                None,
                true,
                None,
                None,
            )
        })
    });
}

fn benchmark_error_response(c: &mut Criterion) {
    let json = r#"{
        "status": "failed:validation",
        "message": "Email already exists",
        "entity_id": null,
        "entity_type": null,
        "entity": null,
        "updated_fields": null,
        "cascade": null,
        "metadata": {"errors": [{"field": "email", "code": "duplicate"}]}
    }"#;

    c.bench_function("error_response", |b| {
        b.iter(|| {
            build_mutation_response(
                black_box(json),
                "createUser",
                "CreateUserSuccess",
                "CreateUserError",
                Some("user"),
                Some("User"),
                None,
                true,
                None,
                None,
            )
        })
    });
}

fn benchmark_array_entities(c: &mut Criterion) {
    let json = r#"[
        {"id": "1", "name": "Alice", "email": "alice@example.com"},
        {"id": "2", "name": "Bob", "email": "bob@example.com"},
        {"id": "3", "name": "Charlie", "email": "charlie@example.com"}
    ]"#;

    c.bench_function("array_entities", |b| {
        b.iter(|| {
            build_mutation_response(
                black_box(json),
                "createUsers",
                "CreateUsersSuccess",
                "CreateUsersError",
                Some("users"),
                Some("User"),
                None,
                true,
                None,
                None,
            )
        })
    });
}

criterion_group!(
    benches,
    benchmark_simple_format,
    benchmark_full_format_with_cascade,
    benchmark_error_response,
    benchmark_array_entities
);
criterion_main!(benches);

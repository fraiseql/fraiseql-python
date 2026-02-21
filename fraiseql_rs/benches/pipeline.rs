use criterion::{Criterion, Throughput, black_box, criterion_group, criterion_main};
// Import the v0.2 unified API
use fraiseql_rs::pipeline::builder::build_graphql_response;

/// Generate small workload: 10 objects, 5 fields each (~1KB total)
fn generate_small_workload() -> Vec<String> {
    (0..10)
        .map(|i| format!(r#"{{"id":{},"first_name":"User{}","last_name":"Last{}","email":"user{}@example.com","is_active":true}}"#, i, i, i, i))
        .collect()
}

/// Generate medium workload: 100 objects, 20 fields each (~50KB total)
fn generate_medium_workload() -> Vec<String> {
    (0..100)
        .map(|i| format!(
            r#"{{"id":{},"first_name":"User{}","last_name":"Last{}","email":"user{}@example.com","phone":"555-{:04}","age":{},"is_active":true,"created_at":"2024-01-{:02}T10:00:00Z","updated_at":"2024-01-{:02}T11:00:00Z","department":"Engineering","manager_id":{},"salary":{},"bonus":{}}}"#,
            i, i, i, i, i, 20 + (i % 50), i % 28 + 1, i % 28 + 1, i % 100, 50000 + (i * 1000), i * 100
        ))
        .collect()
}

/// Generate large workload: 10,000 objects, 20 fields each (~2MB total)
fn generate_large_workload() -> Vec<String> {
    (0..10_000)
        .map(|i| format!(
            r#"{{"id":{},"first_name":"User{}","last_name":"Last{}","email":"user{}@example.com","phone":"555-{:04}","age":{},"is_active":true,"created_at":"2024-01-{:02}T10:00:00Z","updated_at":"2024-01-{:02}T11:00:00Z","department":"Engineering","manager_id":{},"salary":{},"bonus":{}}}"#,
            i, i, i, i, i, 20 + (i % 50), i % 28 + 1, i % 28 + 1, i % 100, 50000 + (i * 1000), i * 100
        ))
        .collect()
}

/// Generate nested workload: User + 50 posts + 10 comments each (~100KB total)
fn generate_nested_workload() -> Vec<String> {
    (0..1)  // Single user for nested test
        .map(|user_id| {
            let posts: Vec<String> = (0..50)
                .map(|post_id| {
                    let comments: Vec<String> = (0..10)
                        .map(|comment_id| format!(
                            r#"{{"id":{},"author_id":{},"content":"Comment {} on post {}","created_at":"2024-01-{:02}T10:00:00Z"}}"#,
                            comment_id + (post_id * 10) + (user_id * 500), user_id, comment_id, post_id, post_id % 28 + 1
                        ))
                        .collect();
                    format!(
                        r#"{{"id":{},"author_id":{},"title":"Post {}","content":"Content for post {}","created_at":"2024-01-{:02}T09:00:00Z","updated_at":"2024-01-{:02}T10:00:00Z","comments":[{}]}}"#,
                        post_id + (user_id * 50), user_id, post_id, post_id, post_id % 28 + 1, post_id % 28 + 1, comments.join(",")
                    )
                })
                .collect();
            format!(
                r#"{{"id":{},"first_name":"User{}","last_name":"Last{}","email":"user{}@example.com","posts":[{}]}}"#,
                user_id, user_id, user_id, user_id, posts.join(",")
            )
        })
        .collect()
}

fn benchmark_small_response(c: &mut Criterion) {
    let json_rows = generate_small_workload();

    let mut group = c.benchmark_group("small_response");
    group.throughput(Throughput::Bytes(json_rows.iter().map(|s| s.len() as u64).sum()));

    group.bench_function("v0.2_zero_copy", |b| {
        b.iter(|| {
            build_graphql_response(
                black_box(json_rows.clone()),
                black_box("users"),
                black_box(Some("User")),
                black_box(None),
                black_box(None),
                black_box(None),
                black_box(None),
            )
        })
    });

    group.finish();
}

fn benchmark_medium_response(c: &mut Criterion) {
    let json_rows = generate_medium_workload();

    let mut group = c.benchmark_group("medium_response");
    group.throughput(Throughput::Bytes(json_rows.iter().map(|s| s.len() as u64).sum()));

    group.bench_function("v0.2_zero_copy", |b| {
        b.iter(|| {
            build_graphql_response(
                black_box(json_rows.clone()),
                black_box("users"),
                black_box(Some("User")),
                black_box(None),
                black_box(None),
                black_box(None),
                black_box(None),
            )
        })
    });

    group.finish();
}

fn benchmark_large_response(c: &mut Criterion) {
    let json_rows = generate_large_workload();

    let mut group = c.benchmark_group("large_response");
    group.throughput(Throughput::Bytes(json_rows.iter().map(|s| s.len() as u64).sum()));
    group.sample_size(10); // Fewer samples for large benchmark

    group.bench_function("v0.2_zero_copy", |b| {
        b.iter(|| {
            build_graphql_response(
                black_box(json_rows.clone()),
                black_box("users"),
                black_box(Some("User")),
                black_box(None),
                black_box(None),
                black_box(None),
                black_box(None),
            )
        })
    });

    group.finish();
}

fn benchmark_nested_response(c: &mut Criterion) {
    let json_rows = generate_nested_workload();

    let mut group = c.benchmark_group("nested_response");
    group.throughput(Throughput::Bytes(json_rows.iter().map(|s| s.len() as u64).sum()));

    group.bench_function("v0.2_zero_copy", |b| {
        b.iter(|| {
            build_graphql_response(
                black_box(json_rows.clone()),
                black_box("users"),
                black_box(Some("User")),
                black_box(None),
                black_box(None),
                black_box(None),
                black_box(None),
            )
        })
    });

    group.finish();
}

criterion_group!(
    benches,
    benchmark_small_response,
    benchmark_medium_response,
    benchmark_large_response,
    benchmark_nested_response
);
criterion_main!(benches);

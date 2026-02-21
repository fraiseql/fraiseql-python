//! Core transformation benchmarks
//!
//! This benchmark tests the zero-copy transformation engine performance
//! without PyO3 overhead, focusing on the raw transformation speed.

use criterion::{Criterion, Throughput, black_box, criterion_group, criterion_main};
use fraiseql_rs::core::{
    arena::Arena,
    transform::{ByteBuf, TransformConfig, ZeroCopyTransformer},
};

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

fn benchmark_zero_copy_small(c: &mut Criterion) {
    let workload = generate_small_workload();
    let total_bytes: u64 = workload.iter().map(|s| s.len() as u64).sum();

    let mut group = c.benchmark_group("zero_copy_small");
    group.throughput(Throughput::Bytes(total_bytes));

    group.bench_function("transform_10_objects", |b| {
        b.iter(|| {
            let arena = Arena::with_capacity(8192);
            let config = TransformConfig {
                add_typename:        true,
                camel_case:          true,
                project_fields:      false,
                add_graphql_wrapper: false,
                max_depth:           64,
            };

            let mut transformer = ZeroCopyTransformer::new(&arena, config, Some("User"), None);

            for json_str in &workload {
                let mut output = ByteBuf::with_estimated_capacity(json_str.len(), &config);
                black_box(transformer.transform_bytes(json_str.as_bytes(), &mut output).unwrap());
            }
        })
    });

    group.finish();
}

fn benchmark_zero_copy_medium(c: &mut Criterion) {
    let workload = generate_medium_workload();
    let total_bytes: u64 = workload.iter().map(|s| s.len() as u64).sum();

    let mut group = c.benchmark_group("zero_copy_medium");
    group.throughput(Throughput::Bytes(total_bytes));

    group.bench_function("transform_100_objects", |b| {
        b.iter(|| {
            let arena = Arena::with_capacity(65536);
            let config = TransformConfig {
                add_typename:        true,
                camel_case:          true,
                project_fields:      false,
                add_graphql_wrapper: false,
                max_depth:           64,
            };

            let mut transformer = ZeroCopyTransformer::new(&arena, config, Some("User"), None);

            for json_str in &workload {
                let mut output = ByteBuf::with_estimated_capacity(json_str.len(), &config);
                black_box(transformer.transform_bytes(json_str.as_bytes(), &mut output).unwrap());
            }
        })
    });

    group.finish();
}

fn benchmark_zero_copy_large(c: &mut Criterion) {
    let workload = generate_large_workload();
    let total_bytes: u64 = workload.iter().map(|s| s.len() as u64).sum();

    let mut group = c.benchmark_group("zero_copy_large");
    group.throughput(Throughput::Bytes(total_bytes));
    group.sample_size(10); // Fewer samples for large benchmark

    group.bench_function("transform_10000_objects", |b| {
        b.iter(|| {
            let arena = Arena::with_capacity(524288); // 512KB arena
            let config = TransformConfig {
                add_typename:        true,
                camel_case:          true,
                project_fields:      false,
                add_graphql_wrapper: false,
                max_depth:           64,
            };

            let mut transformer = ZeroCopyTransformer::new(&arena, config, Some("User"), None);

            for json_str in &workload {
                let mut output = ByteBuf::with_estimated_capacity(json_str.len(), &config);
                black_box(transformer.transform_bytes(json_str.as_bytes(), &mut output).unwrap());
            }
        })
    });

    group.finish();
}

fn benchmark_components(c: &mut Criterion) {
    let json_str = r#"{"user_id":123,"first_name":"John","last_name":"Doe","email":"john@example.com","is_active":true,"created_at":"2024-01-01T10:00:00Z"}"#;

    let mut group = c.benchmark_group("components");

    group.bench_function("arena_allocation", |b| {
        b.iter(|| {
            let arena = Arena::with_capacity(1024);
            black_box(arena.alloc_bytes(256));
        })
    });

    group.bench_function("byte_reader_parsing", |b| {
        b.iter(|| {
            use fraiseql_rs::core::transform::ByteReader;
            let mut reader = ByteReader::new(json_str.as_bytes());
            black_box(reader.expect_byte(b'{').unwrap()); // Skip opening brace
            black_box(reader.read_string().unwrap()); // Read field name "user_id"
            black_box(reader.expect_byte(b':').unwrap()); // Skip colon
            black_box(reader.read_number().unwrap()); // Read number value
        })
    });

    group.bench_function("snake_to_camel", |b| {
        let input = b"user_name_field";
        b.iter(|| {
            let arena = Arena::with_capacity(1024);
            black_box(fraiseql_rs::core::camel::snake_to_camel(input, &arena));
        })
    });

    group.finish();
}

criterion_group!(
    benches,
    benchmark_zero_copy_small,
    benchmark_zero_copy_medium,
    benchmark_zero_copy_large,
    benchmark_components
);
criterion_main!(benches);

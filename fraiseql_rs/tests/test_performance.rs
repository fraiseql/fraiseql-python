use std::time::{Duration, Instant};

// v0.2: old build_list_response has been removed
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

fn benchmark_implementation<F>(
    name: &str,
    _workload: &[String],
    iterations: usize,
    f: F,
) -> (Duration, usize)
where
    F: Fn() -> Result<Vec<u8>, Box<dyn std::error::Error>>,
{
    println!("Benchmarking {} - {} iterations...", name, iterations);

    let mut total_time = Duration::new(0, 0);
    let mut total_bytes = 0;

    for _ in 0..iterations {
        let start = Instant::now();
        match f() {
            Ok(bytes) => {
                let elapsed = start.elapsed();
                total_time += elapsed;
                total_bytes += bytes.len();
            },
            Err(e) => {
                println!("Error in {}: {:?}", name, e);
                return (Duration::new(0, 0), 0);
            },
        }
    }

    let avg_time = total_time / iterations as u32;
    let avg_bytes = total_bytes / iterations;

    println!("  Average time: {:.2}ms", avg_time.as_secs_f64() * 1000.0);
    println!("  Average output: {} bytes", avg_bytes);
    println!("  Throughput: {:.0} ops/sec", 1.0 / avg_time.as_secs_f64());

    (avg_time, avg_bytes)
}

fn main() {
    println!("🚀 FraiseQL Performance Benchmark - Phase 6 Validation");
    println!("======================================================");
    println!();

    // Test small workload
    println!("📊 SMALL WORKLOAD (10 objects, ~1KB)");
    println!("-------------------------------------");
    let small_workload = generate_small_workload();
    let iterations = 1000;

    let (_new_time, new_bytes) =
        benchmark_implementation("v0.2 Zero-Copy", &small_workload, iterations, || {
            build_graphql_response(small_workload.clone(), "users", Some("User"), None, None, None)
                .map_err(|e| Box::new(e) as Box<dyn std::error::Error>)
        });

    println!("  Output size: {} bytes", new_bytes);
    println!();

    // Test medium workload
    println!("📊 MEDIUM WORKLOAD (100 objects, ~50KB)");
    println!("----------------------------------------");
    let medium_workload = generate_medium_workload();
    let iterations = 100;

    let (_new_time, new_bytes) =
        benchmark_implementation("v0.2 Zero-Copy", &medium_workload, iterations, || {
            build_graphql_response(medium_workload.clone(), "users", Some("User"), None, None, None)
                .map_err(|e| Box::new(e) as Box<dyn std::error::Error>)
        });

    println!("  Output size: {} bytes", new_bytes);
    println!();

    println!("✅ Phase 6 Validation Complete!");
    println!("Next: Run memory profiling with `cargo run --bin memory_profile`");
}

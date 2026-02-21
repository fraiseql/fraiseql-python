// v0.2: Only the unified API is available
use fraiseql_rs::pipeline::builder::build_graphql_response;

/// Generate test workload for memory profiling
fn generate_memory_test_workload() -> Vec<String> {
    (0..1000)
        .map(|i| format!(r#"{{"id":{},"first_name":"User{}","last_name":"Last{}","email":"user{}@example.com","is_active":true}}"#, i, i, i, i))
        .collect()
}

#[cfg(feature = "dhat-heap")]
#[global_allocator]
static ALLOC: dhat::Alloc = dhat::Alloc;

fn profile_memory() {
    let json_rows = generate_memory_test_workload();

    println!("=== MEMORY PROFILING: v0.2 ZERO-COPY IMPLEMENTATION ===");
    println!("Workload: 1,000 objects, ~50KB total");
    println!();

    println!("--- ZERO-COPY IMPLEMENTATION ---");
    let result = build_graphql_response(json_rows, "users", Some("User"), None, None, None, None);
    match result {
        Ok(bytes) => {
            println!("✓ Response generated successfully");
            println!("  Output size: {} bytes", bytes.len());
        },
        Err(e) => {
            println!("✗ Error: {:?}", e);
        },
    }
}

fn main() {
    profile_memory();
}

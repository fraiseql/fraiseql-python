// v0.2: Only the unified API is available
use fraiseql_rs::pipeline::builder::build_graphql_response;

fn main() {
    // Simple test data
    let json_rows = vec![
        r#"{"id":1,"first_name":"John","last_name":"Doe","email":"john@example.com"}"#.to_string(),
        r#"{"id":2,"first_name":"Jane","last_name":"Smith","email":"jane@example.com"}"#
            .to_string(),
    ];

    println!("Testing v0.2 zero-copy implementation...");
    let result = build_graphql_response(json_rows, "users", Some("User"), None, None, None, None);
    match result {
        Ok(bytes) => {
            println!("✓ Implementation succeeded");
            println!("Output length: {} bytes", bytes.len());
            // Print first 200 chars
            let output_str = String::from_utf8_lossy(&bytes);
            println!("Output preview: {}...", &output_str[..output_str.len().min(200)]);
        },
        Err(e) => {
            println!("✗ Implementation failed: {:?}", e);
        },
    }
}

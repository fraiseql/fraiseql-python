use fraiseql_rs::core::{
    arena::Arena,
    transform::{ByteBuf, TransformConfig, ZeroCopyTransformer},
};

fn main() {
    println!("🧪 Testing Zero-Copy Transformer - Phase 1 Validation");
    println!("====================================================");
    println!();

    // Test data
    let json_input = r#"{"id":123,"first_name":"John","last_name":"Doe","email":"john@example.com","is_active":true}"#;
    println!("📝 Input JSON: {}", json_input);
    println!();

    // Setup arena
    let arena = Arena::with_capacity(8192);

    // Setup transformer config
    let config = TransformConfig {
        add_typename:        true,
        camel_case:          true,
        project_fields:      false,
        add_graphql_wrapper: false,
    };

    // Create transformer
    let transformer = ZeroCopyTransformer::new(&arena, config, Some("User"), None);

    // Transform
    let mut output = ByteBuf::with_estimated_capacity(json_input.len(), &config);

    match transformer.transform_bytes(json_input.as_bytes(), &mut output) {
        Ok(()) => {
            let result = output.into_vec();
            let result_str = String::from_utf8_lossy(&result);
            println!("✅ Transformation successful!");
            println!("📤 Output: {}", result_str);
            println!("📏 Input size: {} bytes", json_input.len());
            println!("📏 Output size: {} bytes", result.len());
            println!("📈 Overhead: {:.1}x", result.len() as f64 / json_input.len() as f64);
        },
        Err(e) => {
            println!("❌ Transformation failed: {:?}", e);
        },
    }

    println!();
    println!("🎉 Phase 1 Zero-Copy Transformer Test Complete!");
}

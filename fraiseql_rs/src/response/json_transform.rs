//! In-stream JSON transformation (snake_case → camelCase).

use serde_json::{Map, Value};

/// Convert snake_case to camelCase
pub fn to_camel_case(snake: &str) -> String {
    let mut result = String::new();
    let mut capitalize_next = false;

    for c in snake.chars() {
        if c == '_' {
            capitalize_next = true;
        } else if capitalize_next {
            result.push(c.to_uppercase().next().unwrap());
            capitalize_next = false;
        } else {
            result.push(c);
        }
    }

    result
}

/// Transform row from PostgreSQL to GraphQL format with key transformation
pub fn transform_row_keys(row: &Value) -> Value {
    match row {
        Value::Object(map) => {
            let mut new_map = Map::new();
            for (key, value) in map.iter() {
                let camel_key = to_camel_case(key);
                let transformed_value = transform_row_keys(value);
                new_map.insert(camel_key, transformed_value);
            }
            Value::Object(new_map)
        },
        Value::Array(arr) => Value::Array(arr.iter().map(transform_row_keys).collect()),
        other => other.clone(),
    }
}

/// Transform JSONB field (nested) to camelCase
pub fn transform_jsonb_field(field_str: &str) -> Result<Value, serde_json::Error> {
    let value: Value = serde_json::from_str(field_str)?;
    Ok(transform_row_keys(&value))
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn test_snake_to_camel() {
        assert_eq!(to_camel_case("user_id"), "userId");
        assert_eq!(to_camel_case("first_name"), "firstName");
        assert_eq!(to_camel_case("simple"), "simple");
        assert_eq!(to_camel_case("_private"), "_private");
        assert_eq!(to_camel_case("user_email_address"), "userEmailAddress");
    }

    #[test]
    fn test_transform_keys() {
        let row = json!({
            "user_id": 123,
            "first_name": "John",
            "nested_object": {
                "user_email": "john@example.com",
                "last_login_date": "2023-01-01"
            }
        });

        let transformed = transform_row_keys(&row);
        assert_eq!(transformed["userId"], 123);
        assert_eq!(transformed["firstName"], "John");
        assert_eq!(transformed["nestedObject"]["userEmail"], "john@example.com");
        assert_eq!(transformed["nestedObject"]["lastLoginDate"], "2023-01-01");
    }

    #[test]
    fn test_transform_jsonb_field() {
        let jsonb_str = r#"{"user_id": 456, "profile_data": {"first_name": "Jane"}}"#;
        let transformed = transform_jsonb_field(jsonb_str).unwrap();

        assert_eq!(transformed["userId"], 456);
        assert_eq!(transformed["profileData"]["firstName"], "Jane");
    }

    #[test]
    fn test_array_transformation() {
        let row = json!({
            "tags": ["snake_case", "another_tag"],
            "metadata": {
                "user_list": [
                    {"full_name": "Alice", "user_role": "admin"},
                    {"full_name": "Bob", "user_role": "user"}
                ]
            }
        });

        let transformed = transform_row_keys(&row);
        assert_eq!(transformed["tags"][0], "snake_case");
        assert_eq!(transformed["tags"][1], "another_tag");
        assert_eq!(transformed["metadata"]["userList"][0]["fullName"], "Alice");
        assert_eq!(transformed["metadata"]["userList"][0]["userRole"], "admin");
        assert_eq!(transformed["metadata"]["userList"][1]["fullName"], "Bob");
        assert_eq!(transformed["metadata"]["userList"][1]["userRole"], "user");
    }
}

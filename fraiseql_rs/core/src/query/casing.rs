//! Field name case conversion (camelCase → `snake_case`).
//!
//! This module handles converting GraphQL field names (typically camelCase)
//! to `PostgreSQL` column names (typically `snake_case`) to match Python behavior.

/// Convert camelCase or `PascalCase` to `snake_case`.
///
/// This implementation matches Python's behavior for field name conversion.
///
/// # Examples
///
/// ```
/// use fraiseql_rs::query::casing::to_snake_case;
///
/// assert_eq!(to_snake_case("userId"), "user_id");
/// assert_eq!(to_snake_case("createdAt"), "created_at");
/// assert_eq!(to_snake_case("HTTPResponse"), "http_response");
/// assert_eq!(to_snake_case("already_snake"), "already_snake");
/// ```
#[must_use]
pub fn to_snake_case(s: &str) -> String {
    // If already snake_case (no uppercase letters), return as-is
    if !s.chars().any(char::is_uppercase) {
        return s.to_string();
    }

    let mut result = String::with_capacity(s.len() + 5);
    let mut prev_was_upper = false;
    let mut prev_was_lower = false;

    for (i, c) in s.chars().enumerate() {
        if c.is_uppercase() {
            // Add underscore before uppercase if:
            // 1. Not the first character
            // 2. Previous was lowercase OR next is lowercase (handles "HTTPResponse" → "http_response")
            if i > 0 {
                let next_is_lower = s.chars().nth(i + 1).is_some_and(char::is_lowercase);
                if prev_was_lower || (prev_was_upper && next_is_lower) {
                    result.push('_');
                }
            }
            result.push(c.to_ascii_lowercase());
            prev_was_upper = true;
            prev_was_lower = false;
        } else {
            result.push(c);
            prev_was_upper = false;
            prev_was_lower = c.is_lowercase();
        }
    }

    result
}

/// Convert `snake_case` to camelCase.
///
/// This is the reverse operation, used for output formatting.
///
/// # Examples
///
/// ```
/// use fraiseql_rs::query::casing::to_camel_case;
///
/// assert_eq!(to_camel_case("user_id"), "userId");
/// assert_eq!(to_camel_case("created_at"), "createdAt");
/// assert_eq!(to_camel_case("http_response"), "httpResponse");
/// assert_eq!(to_camel_case("alreadyCamel"), "alreadyCamel");
/// ```
#[must_use]
pub fn to_camel_case(s: &str) -> String {
    // If no underscores, assume already camelCase
    if !s.contains('_') {
        return s.to_string();
    }

    let mut result = String::with_capacity(s.len());
    let mut capitalize_next = false;

    for c in s.chars() {
        if c == '_' {
            capitalize_next = true;
        } else if capitalize_next {
            result.push(c.to_ascii_uppercase());
            capitalize_next = false;
        } else {
            result.push(c);
        }
    }

    result
}

/// Normalize a field path for database access.
///
/// This handles dotted paths like "user.profile.name" and converts each segment.
///
/// # Examples
///
/// ```
/// use fraiseql_rs::query::casing::normalize_field_path;
///
/// assert_eq!(normalize_field_path("userId"), "user_id");
/// assert_eq!(normalize_field_path("user.createdAt"), "user.created_at");
/// assert_eq!(normalize_field_path("device.sensor.currentValue"), "device.sensor.current_value");
/// ```
pub fn normalize_field_path(path: &str) -> String {
    if !path.contains('.') {
        return to_snake_case(path);
    }

    path.split('.')
        .map(to_snake_case)
        .collect::<Vec<_>>()
        .join(".")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_simple_camel_to_snake() {
        assert_eq!(to_snake_case("userId"), "user_id");
        assert_eq!(to_snake_case("userName"), "user_name");
        assert_eq!(to_snake_case("firstName"), "first_name");
    }

    #[test]
    fn test_pascal_to_snake() {
        assert_eq!(to_snake_case("UserId"), "user_id");
        assert_eq!(to_snake_case("FirstName"), "first_name");
    }

    #[test]
    fn test_consecutive_capitals() {
        assert_eq!(to_snake_case("HTTPResponse"), "http_response");
        assert_eq!(to_snake_case("XMLParser"), "xml_parser");
        assert_eq!(to_snake_case("IOError"), "io_error");
    }

    #[test]
    fn test_already_snake_case() {
        assert_eq!(to_snake_case("user_id"), "user_id");
        assert_eq!(to_snake_case("first_name"), "first_name");
        assert_eq!(to_snake_case("http_response"), "http_response");
    }

    #[test]
    fn test_mixed_formats() {
        assert_eq!(to_snake_case("user_Id"), "user__id"); // Intentional: respects existing underscores
        assert_eq!(to_snake_case("HTTPStatus_Code"), "http_status__code");
    }

    #[test]
    fn test_single_char() {
        assert_eq!(to_snake_case("a"), "a");
        assert_eq!(to_snake_case("A"), "a");
    }

    #[test]
    fn test_empty_string() {
        assert_eq!(to_snake_case(""), "");
    }

    #[test]
    fn test_numbers() {
        assert_eq!(to_snake_case("user2FA"), "user2_fa");
        assert_eq!(to_snake_case("level99Boss"), "level99_boss");
    }

    #[test]
    fn test_simple_snake_to_camel() {
        assert_eq!(to_camel_case("user_id"), "userId");
        assert_eq!(to_camel_case("first_name"), "firstName");
        assert_eq!(to_camel_case("http_response"), "httpResponse");
    }

    #[test]
    fn test_already_camel_case() {
        assert_eq!(to_camel_case("userId"), "userId");
        assert_eq!(to_camel_case("firstName"), "firstName");
    }

    #[test]
    fn test_multiple_underscores() {
        assert_eq!(to_camel_case("user__id"), "userId");
        assert_eq!(to_camel_case("http___response"), "httpResponse");
    }

    #[test]
    fn test_trailing_underscore() {
        assert_eq!(to_camel_case("user_id_"), "userId");
        assert_eq!(to_camel_case("first_name_"), "firstName");
    }

    #[test]
    fn test_normalize_field_path_simple() {
        assert_eq!(normalize_field_path("userId"), "user_id");
        assert_eq!(normalize_field_path("createdAt"), "created_at");
    }

    #[test]
    fn test_normalize_field_path_nested() {
        assert_eq!(normalize_field_path("user.createdAt"), "user.created_at");
        assert_eq!(
            normalize_field_path("device.sensorData.currentValue"),
            "device.sensor_data.current_value"
        );
    }

    #[test]
    fn test_normalize_field_path_already_snake() {
        assert_eq!(normalize_field_path("user_id"), "user_id");
        assert_eq!(normalize_field_path("user.created_at"), "user.created_at");
    }

    #[test]
    fn test_roundtrip_conversion() {
        let original = "userId";
        let snake = to_snake_case(original);
        let back = to_camel_case(&snake);
        assert_eq!(back, original);

        let original2 = "HTTPResponse";
        let snake2 = to_snake_case(original2);
        assert_eq!(snake2, "http_response");
        let back2 = to_camel_case(&snake2);
        assert_eq!(back2, "httpResponse"); // Note: loses the capitalization pattern
    }

    #[test]
    fn test_real_world_examples() {
        // Common GraphQL field names
        assert_eq!(to_snake_case("createdAt"), "created_at");
        assert_eq!(to_snake_case("updatedAt"), "updated_at");
        assert_eq!(to_snake_case("deletedAt"), "deleted_at");
        assert_eq!(to_snake_case("isActive"), "is_active");
        assert_eq!(to_snake_case("isDeleted"), "is_deleted");
        assert_eq!(to_snake_case("machineId"), "machine_id");
        assert_eq!(to_snake_case("deviceType"), "device_type");
    }
}

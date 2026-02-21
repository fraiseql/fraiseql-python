//! Snake case to camel case conversion (String-based API)
//!
//! This module provides ultra-fast snake_case → camelCase conversion
//! for GraphQL field names.
//!
//! ## Architecture
//!
//! FraiseQL has **two camelCase implementations** serving different needs:
//! - **This module (camel_case.rs)**: String-based API for PyO3 and serde_json
//! - **core::camel**: SIMD-optimized zero-copy API for streaming transformation
//!
//! ## When to Use This Module
//!
//! ✅ **Use `camel_case.rs` when**:
//! - Called from Python via PyO3
//! - Transforming `serde_json::Value` objects
//! - Working with `String` or `&str` types
//! - Need recursive dictionary transformation
//!
//! ❌ **Use `core::camel` instead when**:
//! - Hot path streaming transformation (3-5x faster)
//! - Zero-copy performance required (arena allocation)
//! - Processing byte slices (`&[u8]`)
//!
//! For detailed architecture rationale, see: `docs/camel-case-apis.md`

use pyo3::{
    prelude::*,
    types::{PyDict, PyList},
};

/// Convert a snake_case string to camelCase
///
/// This function is optimized for GraphQL field names which are typically:
/// - Short (< 50 characters)
/// - ASCII only
/// - Few underscores (1-3)
///
/// # Examples
/// - "user_name" → "userName"
/// - "email_address" → "emailAddress"
/// - "_private" → "_private" (leading underscore preserved)
/// - "user" → "user" (single word unchanged)
/// - "user__name" → "userName" (multiple underscores handled)
///
/// # Performance
/// - Pre-allocates string capacity
/// - Single pass through input
/// - Inline hints for hot path
///
/// # Arguments
/// * `s` - The snake_case string to convert
///
/// # Returns
/// The camelCase string
#[inline]
pub fn to_camel_case(s: &str) -> String {
    // Fast path: empty string
    if s.is_empty() {
        return String::new();
    }

    // Pre-allocate with input length (we'll use same or less)
    let mut result = String::with_capacity(s.len());
    let mut capitalize_next = false;
    let mut is_first_char = true;

    for c in s.chars() {
        if c == '_' {
            // If this is the first character, preserve leading underscore
            if is_first_char {
                result.push(c);
            } else {
                // Mark that next character should be capitalized
                capitalize_next = true;
            }
        } else {
            if capitalize_next {
                // Capitalize this character
                // Hot path: most characters are ASCII and single-codepoint
                for upper in c.to_uppercase() {
                    result.push(upper);
                }
                capitalize_next = false;
            } else {
                // Keep character as-is (most common path)
                result.push(c);
            }
            is_first_char = false;
        }
    }

    result
}

/// Convert all keys in a dictionary from snake_case to camelCase
///
/// Creates a new dictionary with transformed keys. Values are preserved unless
/// recursive mode is enabled.
///
/// # Performance
/// - Optimized for GraphQL objects (10-50 fields)
/// - Inline hints for common operations
/// - Minimal allocations
///
/// # Arguments
/// * `py` - Python interpreter reference
/// * `obj` - Python dictionary with snake_case keys
/// * `recursive` - If true, recursively transform nested dicts and lists
///
/// # Returns
/// New dictionary with camelCase keys
#[inline]
pub fn transform_dict_keys(
    py: Python,
    obj: &Bound<'_, PyDict>,
    recursive: bool,
) -> PyResult<Py<PyDict>> {
    let result = PyDict::new(py);

    for (key, value) in obj.iter() {
        // Convert key to string and transform to camelCase
        let key_str: String = key.extract()?;
        let camel_key = to_camel_case(&key_str);

        // Handle value based on recursive flag
        let new_value = if recursive {
            transform_value_recursive(py, &value)?
        } else {
            value.clone().unbind()
        };

        result.set_item(camel_key, new_value)?;
    }

    Ok(result.unbind())
}

/// Recursively transform a value (handles dicts and lists)
///
/// This function handles the recursive transformation of nested structures:
/// - Dictionaries: Transform keys recursively
/// - Lists: Transform each element recursively
/// - Other types: Return as-is
///
/// # Performance
/// - Tail-recursive where possible
/// - Minimal type checking overhead
#[inline]
fn transform_value_recursive(py: Python, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    // Check if it's a dictionary (most common case for nested GraphQL objects)
    if let Ok(dict) = value.downcast::<PyDict>() {
        let transformed = transform_dict_keys(py, dict, true)?;
        return Ok(transformed.into_any());
    }

    // Check if it's a list (common for nested arrays)
    if let Ok(list) = value.downcast::<PyList>() {
        let new_list = PyList::empty(py);
        for item in list.iter() {
            let transformed_item = transform_value_recursive(py, &item)?;
            new_list.append(transformed_item)?;
        }
        return Ok(new_list.unbind().into_any());
    }

    // For other types (int, str, bool, None, etc.), return as-is
    // This is the fast path for leaf values
    Ok(value.clone().unbind())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_basic_conversion() {
        assert_eq!(to_camel_case("user_name"), "userName");
        assert_eq!(to_camel_case("first_name"), "firstName");
        assert_eq!(to_camel_case("email_address"), "emailAddress");
    }

    #[test]
    fn test_single_word() {
        assert_eq!(to_camel_case("user"), "user");
        assert_eq!(to_camel_case("email"), "email");
        assert_eq!(to_camel_case("id"), "id");
    }

    #[test]
    fn test_multiple_underscores() {
        assert_eq!(to_camel_case("user_full_name"), "userFullName");
        assert_eq!(to_camel_case("billing_address_line_1"), "billingAddressLine1");
    }

    #[test]
    fn test_edge_cases() {
        assert_eq!(to_camel_case(""), "");
        assert_eq!(to_camel_case("userName"), "userName"); // Already camelCase
        assert_eq!(to_camel_case("_private"), "_private"); // Leading underscore
        assert_eq!(to_camel_case("_user_name"), "_userName");
        assert_eq!(to_camel_case("user_name_"), "userName"); // Trailing underscore
        assert_eq!(to_camel_case("user__name"), "userName"); // Multiple underscores
    }

    #[test]
    fn test_with_numbers() {
        assert_eq!(to_camel_case("address_line_1"), "addressLine1");
        assert_eq!(to_camel_case("ipv4_address"), "ipv4Address");
        assert_eq!(to_camel_case("user_123_id"), "user123Id");
    }
}

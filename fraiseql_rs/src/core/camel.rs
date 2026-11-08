//! snake_case to camelCase conversion for the zero-copy transformer (byte API)
//!
//! ## Architecture
//!
//! FraiseQL has **two camelCase implementations** serving different needs:
//! - **crate::camel_case**: String-based API for PyO3 and serde_json
//! - **This module (core::camel)**: byte-slice API writing into a caller-owned buffer
//!
//! ## When to Use This Module
//!
//! ✅ **Use `core::camel` when**:
//! - Hot path streaming transformation over byte slices (`&[u8]`)
//! - A scratch buffer can be reused across keys, so converting allocates nothing
//!
//! ❌ **Use `crate::camel_case` instead when**:
//! - Called from Python via PyO3
//! - Working with `String` or `&str` types
//! - Need recursive dictionary transformation
//!
//! For detailed architecture rationale, see: `docs/camel-case-apis.md`

/// Convert snake_case to camelCase into `scratch`, and return the result.
///
/// `scratch` is cleared first and holds the result until the next call, so a caller
/// converting many keys reuses one buffer: once it has grown to the longest key, a
/// conversion allocates nothing. Each underscore is dropped and the byte after it
/// upper-cased (a byte that has no upper case, such as a digit, is kept as is):
/// `user_name` gives `userName`, `a_1b` gives `a1b`.
///
/// # Examples
/// ```
/// use fraiseql_rs::core::snake_to_camel;
///
/// let mut scratch = Vec::new();
/// assert_eq!(snake_to_camel(b"hello_world", &mut scratch), b"helloWorld");
/// assert_eq!(snake_to_camel(b"id", &mut scratch), b"id");
/// ```
pub fn snake_to_camel<'a>(input: &[u8], scratch: &'a mut Vec<u8>) -> &'a [u8] {
    scratch.clear();

    // Fast path: no underscores (the common case)
    if !input.contains(&b'_') {
        scratch.extend_from_slice(input);
        return scratch;
    }

    scratch.reserve(input.len());
    let mut capitalize_next = false;
    for &byte in input {
        if byte == b'_' {
            capitalize_next = true;
        } else if capitalize_next {
            scratch.push(byte.to_ascii_uppercase());
            capitalize_next = false;
        } else {
            scratch.push(byte);
        }
    }
    scratch
}

#[cfg(test)]
mod tests {
    use super::*;

    fn convert(input: &str) -> String {
        let mut scratch = Vec::new();
        String::from_utf8(snake_to_camel(input.as_bytes(), &mut scratch).to_vec()).unwrap()
    }

    #[test]
    fn test_conversions() {
        for (input, expected) in [
            ("", ""),
            ("id", "id"),
            ("user_name", "userName"),
            ("created_at_utc", "createdAtUtc"),
            ("a_1b", "a1b"),
            ("address_line_1", "addressLine1"),
            ("double__underscore", "doubleUnderscore"),
            ("trailing_", "trailing"),
            ("already_Upper", "alreadyUpper"),
        ] {
            assert_eq!(convert(input), expected, "{input}");
        }
    }

    #[test]
    fn test_long_keys() {
        let key = format!("{}_tail", "segment_".repeat(40));
        let expected = format!("segment{}Tail", "Segment".repeat(39));

        assert_eq!(convert(&key), expected);
    }

    #[test]
    fn test_scratch_is_reused_without_carrying_over() {
        let mut scratch = Vec::new();
        assert_eq!(snake_to_camel(b"first_name_of_the_user", &mut scratch), b"firstNameOfTheUser");
        assert_eq!(snake_to_camel(b"id", &mut scratch), b"id");
        assert_eq!(snake_to_camel(b"a_b", &mut scratch), b"aB");
    }

    mod proptests {
        use proptest::prelude::*;

        use super::*;

        proptest! {
            /// Converting keys one after another into one buffer gives each key
            /// its own conversion, as the string API computes it.
            #[test]
            fn sequential_conversions_match_the_string_api(
                keys in prop::collection::vec("[a-z][a-z0-9_]{0,300}", 1..50)
            ) {
                let mut scratch = Vec::new();
                for key in &keys {
                    let converted = snake_to_camel(key.as_bytes(), &mut scratch).to_vec();
                    prop_assert_eq!(converted, crate::camel_case::to_camel_case(key).into_bytes());
                }
            }
        }
    }
}

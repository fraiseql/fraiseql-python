//! Field selection filtering for mutation responses
//!
//! This module provides utilities to filter JSON response objects based on
//! GraphQL field selections extracted from the query.
//!
//! # Overview
//!
//! When a GraphQL mutation includes field selection (e.g., requesting only
//! specific fields from the response object), this module filters the response
//! to include only the requested fields. This reduces response payload size
//! and prevents leakage of unrequested sensitive fields.
//!
//! # Architecture
//!
//! The filtering process is two-layered:
//! 1. **Selection parsing**: Convert string-based field lists to a selection tree
//! 2. **Recursive filtering**: Apply selections recursively to nested objects
//!
//! # Example
//!
//! Given a response:
//! ```json
//! {
//!   "id": "123",
//!   "name": "John",
//!   "email": "john@example.com",
//!   "address": {
//!     "street": "123 Main St",
//!     "city": "New York",
//!     "country": "USA"
//!   }
//! }
//! ```
//!
//! With selections: `["id", "name", "address"]` (via nested selections for address)
//! Result: Only "id", "name", and "address" fields remain.
//!
//! # Performance
//!
//! - Single pass through JSON structure
//! - Minimal memory overhead
//! - Filtering is O(n) where n is response size

use serde_json::{Map, Value};
use std::collections::HashMap;

/// Selection tree for filtering JSON fields
///
/// Represents the field selection from a GraphQL query in a nested structure.
/// A simple boolean `true` means leaf field is selected.
/// A nested map means recursive selection is required.
#[derive(Debug, Clone)]
pub enum SelectionNode {
    /// Leaf field (field with no nested selections)
    Leaf,
    /// Object with field selections
    Object(HashMap<String, SelectionNode>),
}

/// Parse field list from GraphQL selections
///
/// Takes a list of field names and builds a selection node tree.
/// Used for simple, flat field selections.
///
/// # Arguments
/// * `fields` - List of field names to select
///
/// # Returns
/// SelectionNode representing the flat selection
pub fn parse_simple_selections(fields: &[String]) -> SelectionNode {
    if fields.is_empty() {
        return SelectionNode::Leaf;
    }

    let mut map = HashMap::new();
    for field in fields {
        map.insert(field.clone(), SelectionNode::Leaf);
    }

    SelectionNode::Object(map)
}

/// Filter JSON object based on GraphQL selections
///
/// Removes fields that are not included in the selection node.
/// Recursively filters nested objects.
///
/// # Arguments
/// * `value` - The JSON value to filter (typically an object)
/// * `selections` - The selection node indicating which fields to keep
///
/// # Returns
/// Filtered JSON value containing only selected fields
pub fn filter_by_selections(value: &Value, selections: &SelectionNode) -> Value {
    match (value, selections) {
        // No selections means keep nothing (or return leaf)
        (_, SelectionNode::Leaf) => value.clone(),

        // Object filtering
        (Value::Object(obj), SelectionNode::Object(selection_map)) => {
            let mut filtered = Map::new();

            for (key, selection_node) in selection_map {
                if let Some(val) = obj.get(key) {
                    // Recursively filter nested values
                    let filtered_val = filter_by_selections(val, selection_node);
                    filtered.insert(key.clone(), filtered_val);
                }
                // Silently skip fields not in response
            }

            Value::Object(filtered)
        }

        // Array filtering - filter each element
        (Value::Array(arr), selections) => {
            let filtered: Vec<Value> = arr
                .iter()
                .map(|item| filter_by_selections(item, selections))
                .collect();
            Value::Array(filtered)
        }

        // For non-objects, return as-is (primitives don't need filtering)
        (other, _) => other.clone(),
    }
}

/// Filter response fields based on field list
///
/// This is the main entry point for field filtering. Given a response object
/// and a list of fields to include, returns a new response with only those fields.
///
/// # Arguments
/// * `response` - The response object to filter
/// * `field_list` - List of field names to include
///
/// # Returns
/// Filtered response containing only specified fields
///
/// # Example
/// ```ignore
/// let response = json!({
///     "id": "123",
///     "name": "John",
///     "email": "john@example.com"
/// });
///
/// let filtered = filter_response_fields(&response, &vec!["id".to_string(), "name".to_string()]);
/// // Result: {"id": "123", "name": "John"}
/// ```
pub fn filter_response_fields(response: &Value, field_list: &[String]) -> Value {
    if field_list.is_empty() {
        return response.clone();
    }

    let selections = parse_simple_selections(field_list);
    filter_by_selections(response, &selections)
}

/// Filter object fields based on field list
///
/// Filters a JSON object to include only the specified fields.
/// Useful for filtering entity objects within mutation responses.
///
/// # Arguments
/// * `obj` - The object to filter
/// * `field_list` - List of field names to keep
///
/// # Returns
/// Filtered object with only selected fields
pub fn filter_object_fields(obj: &Map<String, Value>, field_list: &[String]) -> Map<String, Value> {
    if field_list.is_empty() {
        return obj.clone();
    }

    let mut filtered = Map::new();

    for field_name in field_list {
        if let Some(value) = obj.get(field_name) {
            filtered.insert(field_name.clone(), value.clone());
        }
    }

    filtered
}

/// Check if any field selections are provided
///
/// Returns true if field_list is not empty, false otherwise.
/// Useful for determining whether to apply filtering.
///
/// # Arguments
/// * `field_list` - Optional field list
///
/// # Returns
/// true if field selections are present, false otherwise
pub fn has_selections(field_list: Option<&[String]>) -> bool {
    field_list.map_or(false, |fields| !fields.is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_simple_selections() {
        let fields = vec!["id".to_string(), "name".to_string()];
        let selection = parse_simple_selections(&fields);

        match selection {
            SelectionNode::Object(map) => {
                assert_eq!(map.len(), 2);
                assert!(map.contains_key("id"));
                assert!(map.contains_key("name"));
            }
            _ => panic!("Expected Object selection"),
        }
    }

    #[test]
    fn test_filter_simple_object() {
        let response = json!({
            "id": "123",
            "name": "John",
            "email": "john@example.com",
            "age": 30
        });

        let fields = vec!["id".to_string(), "name".to_string()];
        let filtered = filter_response_fields(&response, &fields);

        assert_eq!(filtered.get("id").and_then(|v| v.as_str()), Some("123"));
        assert_eq!(filtered.get("name").and_then(|v| v.as_str()), Some("John"));
        assert!(filtered.get("email").is_none());
        assert!(filtered.get("age").is_none());
    }

    #[test]
    fn test_filter_empty_field_list() {
        let response = json!({
            "id": "123",
            "name": "John"
        });

        let filtered = filter_response_fields(&response, &[]);

        // Empty field list means no filtering
        assert_eq!(filtered, response);
    }

    #[test]
    fn test_filter_nonexistent_field() {
        let response = json!({
            "id": "123",
            "name": "John"
        });

        let fields = vec!["id".to_string(), "nonexistent".to_string()];
        let filtered = filter_response_fields(&response, &fields);

        // Only id should be in result
        assert_eq!(filtered.get("id").and_then(|v| v.as_str()), Some("123"));
        assert_eq!(filtered.as_object().unwrap().len(), 1);
    }

    #[test]
    fn test_filter_array_values() {
        let response = json!({
            "items": [
                {"id": "1", "name": "Item 1", "hidden": "secret1"},
                {"id": "2", "name": "Item 2", "hidden": "secret2"}
            ]
        });

        let fields = vec!["items".to_string()];
        let filtered = filter_response_fields(&response, &fields);

        let items = filtered.get("items").and_then(|v| v.as_array());
        assert!(items.is_some());
        assert_eq!(items.unwrap().len(), 2);
    }

    #[test]
    fn test_has_selections() {
        assert!(!has_selections(None));
        assert!(!has_selections(Some(&[])));
        assert!(has_selections(Some(&vec!["id".to_string()])));
    }
}

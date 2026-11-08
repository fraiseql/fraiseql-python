//! Entity Field Filtering
//!
//! Filters entity objects based on GraphQL field selections to reduce payload size
//! and respect GraphQL query semantics for nested entity fields.
//!
//! Related to GitHub issue #525.

use std::collections::HashMap;

use serde_json::{Map, Value, json};

/// Filter entity fields based on GraphQL selections
///
/// Recursively filters entity objects to include only fields that were selected
/// in the GraphQL query. This reduces response payload size and ensures mutations
/// behave consistently with queries.
///
/// # Arguments
///
/// * `entity` - The entity value to filter (can be object, array, primitive, or null)
/// * `selections` - JSON object describing field selections with structure: ```json { "fields":
///   ["id", "name", "address"], "address": { "fields": ["id", "city"] } } ```
///
/// # Returns
///
/// Filtered entity with only selected fields. Returns original entity for:
/// - Null selections (backward compatibility)
/// - Empty field arrays (GraphQL default behavior)
/// - Non-object entities (arrays, primitives, null)
///
/// # Examples
///
/// ```
/// use serde_json::json;
/// use fraiseql_rs::mutation::filter_entity_fields;
///
/// let entity = json!({
///     "id": "loc-123",
///     "name": "Warehouse A",
///     "level": "floor-1",
///     "has_elevator": true,
/// });
///
/// let selections = json!({
///     "fields": ["id", "name"]
/// });
///
/// let filtered = filter_entity_fields(&entity, &selections);
/// assert_eq!(filtered["id"], "loc-123");
/// assert_eq!(filtered["name"], "Warehouse A");
/// assert!(filtered.get("level").is_none());
/// ```
pub fn filter_entity_fields(entity: &Value, selections: &Value) -> Value {
    // Handle null or missing selections - return entity unchanged (backward compat)
    if selections.is_null() {
        return entity.clone();
    }

    // Only filter object entities
    let Value::Object(entity_map) = entity else {
        // Arrays, primitives, null - return unchanged
        return entity.clone();
    };

    // Extract fields array from selections
    let Some(selections_obj) = selections.as_object() else {
        // Invalid selections format - return entity unchanged
        return entity.clone();
    };

    let Some(fields_value) = selections_obj.get("fields") else {
        // No fields specified - return all
        return entity.clone();
    };

    let Some(fields) = fields_value.as_array() else {
        // Invalid fields format - return all
        return entity.clone();
    };

    // Empty fields array - GraphQL default behavior is to return all fields
    if fields.is_empty() {
        return entity.clone();
    }

    // Build filtered object with only selected fields
    let mut filtered = Map::new();

    // Check if selections specify a type name for __typename injection
    let type_name = selections_obj.get("__type").and_then(|v| v.as_str());

    // ALWAYS preserve or add __typename (GraphQL introspection field)
    // Priority: 1) existing __typename, 2) __type from selections
    if let Some(typename_val) = entity_map.get("__typename") {
        // Already exists in entity, preserve it
        filtered.insert("__typename".to_string(), typename_val.clone());
    } else if let Some(type_name) = type_name {
        // Not in entity, but we have type info from selections - add it
        filtered.insert("__typename".to_string(), json!(type_name));
    }

    for field_value in fields {
        let Some(field_name) = field_value.as_str() else {
            continue; // Skip non-string field names
        };

        // Skip __typename since we already added it above
        if field_name == "__typename" {
            continue;
        }

        // Get field value from entity
        let Some(field_val) = entity_map.get(field_name) else {
            continue; // Skip fields not in entity (silently ignore)
        };

        // Check if this field has nested selections
        if let Some(nested_selections) = selections_obj.get(field_name) {
            // Recursively filter nested object (will inject __typename if __type present)
            let filtered_nested = filter_entity_fields(field_val, nested_selections);
            filtered.insert(field_name.to_string(), filtered_nested);
        } else {
            // Leaf field - include as-is
            filtered.insert(field_name.to_string(), field_val.clone());
        }
    }

    Value::Object(filtered)
}

/// Project a value onto a selection from the selection document (format 2).
///
/// A selection is `{"fields": [{"name", "alias", "selections"?}], "__type"?, "__on"?}`.
/// The result holds only the selected fields, each under its `alias` (the response
/// key), so it can go to the client as is:
///
/// - an array is projected element by element, at any depth;
/// - an object's type is its `__typename`, else the selection's `__type`. When
///   `__on` has an entry for that type, its field list is used, else `fields`. The
///   object keeps `__typename` when its type is known, and `__typename` selected
///   under an alias is written under that alias. A field missing from the data is
///   skipped. A selection without `fields` yields `__typename` alone;
/// - anything else is returned as is.
///
/// # Examples
///
/// ```
/// use serde_json::json;
/// use fraiseql_rs::mutation::project_selection;
///
/// let tags = json!([{"id": "t1", "secret": "x"}]);
/// let selection = json!({"__type": "Tag", "fields": [{"name": "id", "alias": "key"}]});
///
/// assert_eq!(project_selection(tags, &selection), json!([{"__typename": "Tag", "key": "t1"}]));
/// ```
pub fn project_selection(value: Value, selection: &Value) -> Value {
    project_selection_with(value, selection, false)
}

/// [`project_selection`], where `typename_where_selected` writes `__typename` only
/// where the selection has it (under its alias): the response then holds exactly
/// the selected fields. An object's type still picks its `__on` fields.
pub fn project_selection_with(
    value: Value,
    selection: &Value,
    typename_where_selected: bool,
) -> Value {
    match value {
        Value::Array(items) => Value::Array(
            items
                .into_iter()
                .map(|item| project_selection_with(item, selection, typename_where_selected))
                .collect(),
        ),
        Value::Object(map) => project_object(map, selection, typename_where_selected),
        other => other,
    }
}

fn project_object(
    mut map: Map<String, Value>,
    selection: &Value,
    typename_where_selected: bool,
) -> Value {
    let type_name = map
        .get("__typename")
        .and_then(Value::as_str)
        .or_else(|| selection.get("__type").and_then(Value::as_str))
        .map(str::to_owned);
    let fields = type_name
        .as_deref()
        .and_then(|name| selection.get("__on").and_then(|on| on.get(name)))
        .or_else(|| selection.get("fields"))
        .and_then(Value::as_array);

    // A field selected under several aliases is read once per alias: the values are
    // moved out of the object, and cloned while another alias still needs them
    let mut uses: HashMap<&str, usize> = HashMap::new();
    for field in fields.into_iter().flatten() {
        if let Some(name) = field.get("name").and_then(Value::as_str) {
            *uses.entry(name).or_default() += 1;
        }
    }

    let mut projected = Map::new();
    if let (false, Some(type_name)) = (typename_where_selected, &type_name) {
        projected.insert("__typename".to_string(), json!(type_name));
    }
    for field in fields.into_iter().flatten() {
        let Some(name) = field.get("name").and_then(Value::as_str) else {
            continue;
        };
        let alias = field.get("alias").and_then(Value::as_str).unwrap_or(name);
        if name == "__typename" {
            if let Some(type_name) = &type_name {
                projected.insert(alias.to_string(), json!(type_name));
            }
            continue;
        }
        let remaining = uses.get_mut(name).map_or(0, |count| {
            *count -= 1;
            *count
        });
        let field_value = if remaining > 0 {
            map.get(name).cloned()
        } else {
            map.remove(name)
        };
        let Some(field_value) = field_value else {
            continue;
        };
        let value = match field.get("selections") {
            Some(sub_selection) if !sub_selection.is_null() => {
                project_selection_with(field_value, sub_selection, typename_where_selected)
            },
            _ => field_value,
        };
        projected.insert(alias.to_string(), value);
    }
    Value::Object(projected)
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn test_project_writes_response_keys() {
        let value = json!({"id": "l1", "name": "HQ", "secret": "x"});
        let selection = json!({
            "__type": "Location",
            "fields": [{"name": "id", "alias": "ident"}, {"name": "id", "alias": "id"}],
        });

        assert_eq!(
            project_selection(value, &selection),
            json!({"__typename": "Location", "ident": "l1", "id": "l1"})
        );
    }

    #[test]
    fn test_project_filters_nested_lists() {
        let value = json!({"grid": [[{"id": "t1", "secret": "x"}]]});
        let selection = json!({"fields": [{
            "name": "grid", "alias": "grid",
            "selections": {"__type": "Tag", "fields": [{"name": "id", "alias": "id"}]},
        }]});

        assert_eq!(
            project_selection(value, &selection),
            json!({"grid": [[{"__typename": "Tag", "id": "t1"}]]})
        );
    }

    #[test]
    fn test_project_picks_fields_by_typename() {
        let value = json!({"__typename": "Org", "name": "n", "title": "t"});
        let selection = json!({
            "fields": [{"name": "name", "alias": "name"}, {"name": "title", "alias": "title"}],
            "__on": {"Org": [{"name": "title", "alias": "title"}]},
        });

        assert_eq!(
            project_selection(value, &selection),
            json!({"__typename": "Org", "title": "t"})
        );
    }

    #[test]
    fn test_project_without_fields_keeps_only_typename() {
        let value = json!({"__typename": "Location", "secret": "x"});

        assert_eq!(project_selection(value, &json!({})), json!({"__typename": "Location"}));
    }

    #[test]
    fn test_filter_simple_fields() {
        let entity = json!({
            "id": "123",
            "name": "Test",
            "extra": "Should be filtered",
        });

        let selections = json!({
            "fields": ["id", "name"]
        });

        let result = filter_entity_fields(&entity, &selections);

        assert_eq!(result["id"], "123");
        assert_eq!(result["name"], "Test");
        assert!(result.get("extra").is_none());
    }

    #[test]
    fn test_filter_nested_fields() {
        let entity = json!({
            "id": "123",
            "address": {
                "id": "addr-1",
                "city": "Paris",
                "postal_code": "75001",
            }
        });

        let selections = json!({
            "fields": ["id", "address"],
            "address": {
                "fields": ["id", "city"]
            }
        });

        let result = filter_entity_fields(&entity, &selections);

        assert_eq!(result["id"], "123");
        assert_eq!(result["address"]["id"], "addr-1");
        assert_eq!(result["address"]["city"], "Paris");
        assert!(result["address"].get("postal_code").is_none());
    }

    #[test]
    fn test_null_selections_returns_all() {
        let entity = json!({"id": "123", "name": "Test"});
        let selections = Value::Null;

        let result = filter_entity_fields(&entity, &selections);

        assert_eq!(result["id"], "123");
        assert_eq!(result["name"], "Test");
    }

    #[test]
    fn test_empty_fields_returns_all() {
        let entity = json!({"id": "123", "name": "Test"});
        let selections = json!({"fields": []});

        let result = filter_entity_fields(&entity, &selections);

        assert_eq!(result["id"], "123");
        assert_eq!(result["name"], "Test");
    }

    #[test]
    fn test_non_object_entity_unchanged() {
        // Array
        let entity = json!([1, 2, 3]);
        let selections = json!({"fields": ["id"]});
        let result = filter_entity_fields(&entity, &selections);
        assert!(result.is_array());

        // Primitive
        let entity = json!("string");
        let result = filter_entity_fields(&entity, &selections);
        assert_eq!(result, "string");

        // Null
        let entity = Value::Null;
        let result = filter_entity_fields(&entity, &selections);
        assert!(result.is_null());
    }

    #[test]
    fn test_deeply_nested() {
        let entity = json!({
            "id": "1",
            "a": {
                "id": "2",
                "b": {
                    "id": "3",
                    "c": "value",
                }
            }
        });

        let selections = json!({
            "fields": ["a"],
            "a": {
                "fields": ["b"],
                "b": {
                    "fields": ["c"]
                }
            }
        });

        let result = filter_entity_fields(&entity, &selections);

        assert!(result.get("id").is_none());
        assert_eq!(result["a"]["b"]["c"], "value");
        assert!(result["a"].get("id").is_none());
        assert!(result["a"]["b"].get("id").is_none());
    }

    #[test]
    fn test_typename_always_preserved() {
        // __typename should be preserved even when not in selection
        let entity = json!({
            "__typename": "User",
            "id": "123",
            "name": "John",
            "email": "john@example.com",
        });

        let selections = json!({
            "fields": ["id", "name"]
        });

        let result = filter_entity_fields(&entity, &selections);

        // __typename should be present
        assert_eq!(result["__typename"], "User");
        // Selected fields should be present
        assert_eq!(result["id"], "123");
        assert_eq!(result["name"], "John");
        // Unselected field should be filtered out
        assert!(result.get("email").is_none());
    }

    #[test]
    fn test_typename_preserved_in_nested_objects() {
        let entity = json!({
            "__typename": "User",
            "id": "123",
            "address": {
                "__typename": "Address",
                "id": "addr-1",
                "city": "Paris",
                "country": "France",
            }
        });

        let selections = json!({
            "fields": ["id", "address"],
            "address": {
                "fields": ["id", "city"]
            }
        });

        let result = filter_entity_fields(&entity, &selections);

        // Top-level __typename preserved
        assert_eq!(result["__typename"], "User");
        assert_eq!(result["id"], "123");

        // Nested __typename preserved
        assert_eq!(result["address"]["__typename"], "Address");
        assert_eq!(result["address"]["id"], "addr-1");
        assert_eq!(result["address"]["city"], "Paris");
        // Unselected nested field filtered out
        assert!(result["address"].get("country").is_none());
    }

    #[test]
    fn test_typename_added_for_nested_objects() {
        // FIX VERIFICATION: Nested objects get __typename from __type in selections
        // This simulates the real scenario where transform_value() doesn't add __typename,
        // but we have type information from Python's schema extraction
        let entity = json!({
            "__typename": "Location",
            "id": "loc-123",
            "name": "Warehouse A",
            "address": {
                // NOTE: __typename is MISSING here (as it comes from DB)
                "id": "addr-1",
                "formatted": "3 quai de la Fosse<br>44000 Nantes",
                "city": "Nantes",
                "country": "France",
            }
        });

        let selections = json!({
            "fields": ["id", "name", "address"],
            "address": {
                "fields": ["id", "formatted"],
                "__type": "PublicAddress"  // ← Type info from Python schema extraction
            }
        });

        let result = filter_entity_fields(&entity, &selections);

        // Top-level __typename preserved
        assert_eq!(result["__typename"], "Location");
        assert_eq!(result["id"], "loc-123");
        assert_eq!(result["name"], "Warehouse A");

        // Nested object fields are present
        assert_eq!(result["address"]["id"], "addr-1");
        assert_eq!(result["address"]["formatted"], "3 quai de la Fosse<br>44000 Nantes");

        // ✅ FIX: __typename should now be added from __type in selections
        assert_eq!(
            result["address"]["__typename"], "PublicAddress",
            "Nested address object should have __typename from __type in selections"
        );

        // Verify filtering still works
        assert!(result["address"].get("city").is_none());
        assert!(result["address"].get("country").is_none());
    }

    #[test]
    fn test_deeply_nested_typename() {
        // Test that __typename injection works for deeply nested objects
        let entity = json!({
            "__typename": "Location",
            "id": "loc-1",
            "address": {
                "id": "addr-1",
                "city": {
                    "id": "city-1",
                    "name": "Nantes",
                    "country": "France"
                }
            }
        });

        let selections = json!({
            "fields": ["id", "address"],
            "__type": "Location",
            "address": {
                "fields": ["id", "city"],
                "__type": "PublicAddress",
                "city": {
                    "fields": ["id", "name"],
                    "__type": "City"
                }
            }
        });

        let result = filter_entity_fields(&entity, &selections);

        // All levels should have __typename
        assert_eq!(result["__typename"], "Location");
        assert_eq!(result["address"]["__typename"], "PublicAddress");
        assert_eq!(result["address"]["city"]["__typename"], "City");

        // Verify filtering works at all levels
        assert!(result["address"]["city"].get("country").is_none());
    }

    #[test]
    fn test_backward_compatibility_without_type_info() {
        // Ensure backward compatibility when __type is not provided
        let entity = json!({
            "__typename": "Location",
            "id": "loc-1",
            "address": {
                "id": "addr-1",
                "formatted": "3 quai"
            }
        });

        let selections = json!({
            "fields": ["id", "address"],
            "address": {
                "fields": ["id", "formatted"]
                // No __type specified
            }
        });

        let result = filter_entity_fields(&entity, &selections);

        // Top-level __typename preserved
        assert_eq!(result["__typename"], "Location");

        // Nested object fields present
        assert_eq!(result["address"]["id"], "addr-1");
        assert_eq!(result["address"]["formatted"], "3 quai");

        // Without __type, __typename won't be added (backward compatible)
        assert!(result["address"].get("__typename").is_none());
    }
}

//! Unit tests for cascade filtering

use super::*;

#[test]
fn test_no_selections_returns_original() {
    let cascade = r#"{"updated": [], "deleted": []}"#;
    let result = filter_cascade_data(cascade, None).unwrap();
    assert_eq!(result, cascade);
}

#[test]
fn test_empty_selections_filters_all_fields() {
    let cascade = r#"{"updated": [], "deleted": [], "invalidations": []}"#;
    let selections = r#"{"fields": []}"#;

    let result = filter_cascade_data(cascade, Some(selections)).unwrap();
    let v: Value = serde_json::from_str(&result).unwrap();
    let obj = v.as_object().unwrap();

    // All fields should be removed
    assert_eq!(obj.len(), 0);
}

#[test]
fn test_filter_updated_item_fields() {
    let cascade = r#"{
        "updated": [{
            "__typename": "Post",
            "id": "1",
            "operation": "CREATED",
            "entity": {"id": "1"}
        }]
    }"#;

    let selections = r#"{
        "fields": ["updated"],
        "updated": {
            "fields": ["__typename", "id"]
        }
    }"#;

    let result = filter_cascade_data(cascade, Some(selections)).unwrap();
    let v: Value = serde_json::from_str(&result).unwrap();
    let item = &v["updated"][0];

    assert!(item.get("__typename").is_some());
    assert!(item.get("id").is_some());
    assert!(item.get("operation").is_none());
    assert!(item.get("entity").is_none());
}

#[test]
fn test_filter_deleted_fields() {
    let cascade = r#"{
        "deleted": [
            {"__typename": "Post", "id": "1", "extra": "data"}
        ]
    }"#;

    let selections = r#"{
        "fields": ["deleted"],
        "deleted": {
            "fields": ["__typename", "id"]
        }
    }"#;

    let result = filter_cascade_data(cascade, Some(selections)).unwrap();
    let v: Value = serde_json::from_str(&result).unwrap();
    let item = &v["deleted"][0];

    assert!(item.get("__typename").is_some());
    assert!(item.get("id").is_some());
    assert!(item.get("extra").is_none());
}

#[test]
fn test_filter_invalidations_fields() {
    let cascade = r#"{
        "invalidations": [
            {
                "queryName": "posts",
                "strategy": "INVALIDATE",
                "scope": "PREFIX",
                "extra": "data"
            }
        ]
    }"#;

    let selections = r#"{
        "fields": ["invalidations"],
        "invalidations": {
            "fields": ["queryName", "strategy"]
        }
    }"#;

    let result = filter_cascade_data(cascade, Some(selections)).unwrap();
    let v: Value = serde_json::from_str(&result).unwrap();
    let item = &v["invalidations"][0];

    assert!(item.get("queryName").is_some());
    assert!(item.get("strategy").is_some());
    assert!(item.get("scope").is_none());
    assert!(item.get("extra").is_none());
}

#[test]
fn test_filter_metadata_fields() {
    let cascade = r#"{
        "metadata": {
            "timestamp": "2025-11-13T10:00:00Z",
            "affectedCount": 2,
            "depth": 3,
            "transactionId": "123456789"
        }
    }"#;

    let selections = r#"{
        "fields": ["metadata"],
        "metadata": {
            "fields": ["timestamp", "affectedCount"]
        }
    }"#;

    let result = filter_cascade_data(cascade, Some(selections)).unwrap();
    let v: Value = serde_json::from_str(&result).unwrap();
    let metadata = v["metadata"].as_object().unwrap();

    assert!(metadata.get("timestamp").is_some());
    assert!(metadata.get("affectedCount").is_some());
    assert!(metadata.get("depth").is_none()); // Not selected
    assert!(metadata.get("transactionId").is_none()); // Not selected
}

#[test]
fn test_filter_metadata_with_new_spec_fields() {
    let cascade = r#"{
        "metadata": {
            "timestamp": "2025-12-15T10:00:00Z",
            "affectedCount": 5,
            "depth": 2,
            "transactionId": "987654321"
        }
    }"#;

    // Client requests only depth and transactionId
    let selections = r#"{
        "fields": ["metadata"],
        "metadata": {
            "fields": ["depth", "transactionId"]
        }
    }"#;

    let result = filter_cascade_data(cascade, Some(selections)).unwrap();
    let v: Value = serde_json::from_str(&result).unwrap();
    let metadata = v["metadata"].as_object().unwrap();

    assert!(metadata.get("timestamp").is_none()); // Not selected
    assert!(metadata.get("affectedCount").is_none()); // Not selected
    assert_eq!(metadata.get("depth").unwrap(), 2);
    assert_eq!(metadata.get("transactionId").unwrap(), "987654321");
}

#[test]
fn test_filter_metadata_all_spec_fields() {
    let cascade = r#"{
        "metadata": {
            "timestamp": "2025-12-15T10:00:00Z",
            "affectedCount": 10,
            "depth": 4,
            "transactionId": "txn_abc123"
        }
    }"#;

    // Client requests all spec fields
    let selections = r#"{
        "fields": ["metadata"],
        "metadata": {
            "fields": ["timestamp", "affectedCount", "depth", "transactionId"]
        }
    }"#;

    let result = filter_cascade_data(cascade, Some(selections)).unwrap();
    let v: Value = serde_json::from_str(&result).unwrap();
    let metadata = v["metadata"].as_object().unwrap();

    assert_eq!(metadata.len(), 4);
    assert_eq!(metadata.get("timestamp").unwrap(), "2025-12-15T10:00:00Z");
    assert_eq!(metadata.get("affectedCount").unwrap(), 10);
    assert_eq!(metadata.get("depth").unwrap(), 4);
    assert_eq!(metadata.get("transactionId").unwrap(), "txn_abc123");
}

#[test]
fn test_filter_all_cascade_fields() {
    let cascade = r#"{
        "updated": [
            {"__typename": "Post", "id": "1", "entity": {"id": "1", "title": "Hello"}}
        ],
        "deleted": [
            {"__typename": "Comment", "id": "2"}
        ],
        "invalidations": [
            {"queryName": "posts", "strategy": "INVALIDATE"}
        ],
        "metadata": {
            "timestamp": "2025-11-13T10:00:00Z",
            "affectedCount": 3
        }
    }"#;

    let selections = r#"{
        "fields": ["updated", "deleted", "invalidations", "metadata"],
        "updated": {
            "fields": ["__typename", "id"]
        },
        "deleted": {
            "fields": ["__typename", "id"]
        },
        "invalidations": {
            "fields": ["queryName"]
        },
        "metadata": {
            "fields": ["affectedCount"]
        }
    }"#;

    let result = filter_cascade_data(cascade, Some(selections)).unwrap();
    let v: Value = serde_json::from_str(&result).unwrap();

    // Check all fields present
    assert!(v.get("updated").is_some());
    assert!(v.get("deleted").is_some());
    assert!(v.get("invalidations").is_some());
    assert!(v.get("metadata").is_some());

    // Check filtering worked
    let updated_item = &v["updated"][0];
    assert_eq!(updated_item.as_object().unwrap().len(), 2);
    assert!(updated_item.get("entity").is_none());

    let deleted_item = &v["deleted"][0];
    assert_eq!(deleted_item.as_object().unwrap().len(), 2);

    let inv_item = &v["invalidations"][0];
    assert_eq!(inv_item.as_object().unwrap().len(), 1);

    let metadata = v["metadata"].as_object().unwrap();
    assert_eq!(metadata.len(), 1);
}

#[test]
fn test_invalid_cascade_json() {
    let cascade = r#"invalid json"#;
    let selections = r#"{"fields": []}"#;

    let result = filter_cascade_data(cascade, Some(selections));
    assert!(result.is_err());
    assert!(result.unwrap_err().contains("Invalid cascade JSON"));
}

#[test]
fn test_invalid_selections_json() {
    let cascade = r#"{"updated": []}"#;
    let selections = r#"invalid json"#;

    let result = filter_cascade_data(cascade, Some(selections));
    assert!(result.is_err());
    assert!(result.unwrap_err().contains("Invalid cascade selections JSON"));
}

#[test]
fn test_empty_cascade() {
    let cascade = r#"{}"#;
    let selections = r#"{"fields": ["updated", "deleted"]}"#;

    let result = filter_cascade_data(cascade, Some(selections)).unwrap();
    let v: Value = serde_json::from_str(&result).unwrap();
    let obj = v.as_object().unwrap();

    // No fields match, empty object
    assert_eq!(obj.len(), 0);
}

#[test]
fn test_large_cascade_payload() {
    // Generate large cascade with 100 entities
    let mut updated = Vec::new();
    for i in 0..100 {
        updated.push(format!(
            r#"{{"__typename": "Post", "id": "{}", "entity": {{"id": "{}", "title": "Title {}", "content": "Content {}"}}}}"#,
            i, i, i, i
        ));
    }

    let cascade = format!(r#"{{"updated": [{}]}}"#, updated.join(","));

    let selections = r#"{
        "fields": ["updated"],
        "updated": {
            "fields": ["__typename", "id"]
        }
    }"#;

    let result = filter_cascade_data(&cascade, Some(selections)).unwrap();
    let v: Value = serde_json::from_str(&result).unwrap();
    let updated_arr = v["updated"].as_array().unwrap();

    assert_eq!(updated_arr.len(), 100);

    // Verify filtering worked on all items
    for item in updated_arr {
        assert!(item.get("id").is_some());
        assert!(item.get("__typename").is_some());
        assert!(item.get("entity").is_none());
    }
}

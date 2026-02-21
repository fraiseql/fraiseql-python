//! Test suite for GraphQL alias transformation
//!
//! This module tests the ability to apply GraphQL field aliases during JSON transformation.
//! Aliases allow clients to rename fields in the response, enabling multiple queries for
//! the same field with different arguments.
//!
//! Examples:
//! ```graphql
//! query {
//!   user {
//!     name
//!     profilePic: profile_image  # alias: profilePic
//!     posts {
//!       author: author_name      # alias: author
//!     }
//!   }
//! }
//! ```
//!
//! Expected transformation:
//! ```json
//! {
//!   "__typename": "User",
//!   "name": "John",
//!   "profilePic": "avatar.jpg",  // ← alias applied instead of "profileImage"
//!   "posts": [{
//!     "__typename": "Post",
//!     "author": "Jane"           // ← alias applied instead of "authorName"
//!   }]
//! }
//! ```

use fraiseql_rs::{json_transform::transform_with_selections, schema_registry::SchemaRegistry};
use serde_json::{Value, json};

/// Helper to create a test schema registry
fn create_test_schema() -> SchemaRegistry {
    let schema_ir = r#"{
        "version": "1.0",
        "features": ["type_resolution", "aliases"],
        "types": {
            "User": {
                "fields": {
                    "id": {
                        "type_name": "String",
                        "is_nested_object": false,
                        "is_list": false
                    },
                    "user_name": {
                        "type_name": "String",
                        "is_nested_object": false,
                        "is_list": false
                    },
                    "profile_image": {
                        "type_name": "String",
                        "is_nested_object": false,
                        "is_list": false
                    },
                    "posts": {
                        "type_name": "Post",
                        "is_nested_object": true,
                        "is_list": true
                    }
                }
            },
            "Post": {
                "fields": {
                    "id": {
                        "type_name": "String",
                        "is_nested_object": false,
                        "is_list": false
                    },
                    "title": {
                        "type_name": "String",
                        "is_nested_object": false,
                        "is_list": false
                    },
                    "author_name": {
                        "type_name": "String",
                        "is_nested_object": false,
                        "is_list": false
                    },
                    "comments": {
                        "type_name": "Comment",
                        "is_nested_object": true,
                        "is_list": true
                    }
                }
            },
            "Comment": {
                "fields": {
                    "id": {
                        "type_name": "String",
                        "is_nested_object": false,
                        "is_list": false
                    },
                    "comment_text": {
                        "type_name": "String",
                        "is_nested_object": false,
                        "is_list": false
                    },
                    "commenter_name": {
                        "type_name": "String",
                        "is_nested_object": false,
                        "is_list": false
                    }
                }
            }
        }
    }"#;

    SchemaRegistry::from_json(schema_ir).expect("Failed to create test schema")
}

/// Helper to create a FieldSelection structure
///
/// FieldSelection structure (matches Python FieldSelection dataclass):
/// {
///   "materialized_path": "user.posts.author_name",
///   "alias": "postAuthor",
///   "type_info": {
///     "type_name": "String",
///     "is_list": false,
///     "is_nested_object": false
///   }
/// }
fn make_selection(path: &str, alias: &str, type_name: &str, is_list: bool) -> Value {
    json!({
        "materialized_path": path,
        "alias": alias,
        "type_info": {
            "type_name": type_name,
            "is_list": is_list,
            "is_nested_object": false
        }
    })
}

#[test]
fn test_basic_alias_at_root_level() {
    let registry = create_test_schema();

    // Input: Simple user object with snake_case fields
    let input = json!({
        "id": "1",
        "user_name": "John Doe"
    });

    // Field selections: Apply alias to user_name
    let selections = vec![
        make_selection("id", "id", "String", false),
        make_selection("user_name", "username", "String", false), // alias: username
    ];

    // Transform with aliases
    let result = transform_with_selections(&input, "User", &selections, &registry);

    // Expected: alias "username" instead of camelCase "userName"
    assert_eq!(result["__typename"], "User");
    assert_eq!(result["id"], "1");
    assert_eq!(result["username"], "John Doe"); // ← aliased field
    assert!(result.get("userName").is_none()); // ← original camelCase not present
}

#[test]
fn test_nested_alias_single_level() {
    let registry = create_test_schema();

    // Input: User with profile_image
    let input = json!({
        "id": "1",
        "profile_image": "avatar.jpg"
    });

    // Field selections: Apply alias to profile_image
    let selections = vec![
        make_selection("id", "id", "String", false),
        make_selection("profile_image", "avatar", "String", false), // alias: avatar
    ];

    let result = transform_with_selections(&input, "User", &selections, &registry);

    assert_eq!(result["__typename"], "User");
    assert_eq!(result["id"], "1");
    assert_eq!(result["avatar"], "avatar.jpg"); // ← aliased field
    assert!(result.get("profileImage").is_none());
}

#[test]
fn test_alias_in_nested_object() {
    let registry = create_test_schema();

    // Input: User with nested posts
    let input = json!({
        "id": "1",
        "user_name": "John",
        "posts": [{
            "id": "10",
            "title": "My Post",
            "author_name": "Jane Doe"
        }]
    });

    // Field selections: Apply alias deep in nested structure
    let selections = vec![
        make_selection("id", "id", "String", false),
        make_selection("user_name", "userName", "String", false),
        make_selection("posts.id", "posts.id", "String", false),
        make_selection("posts.title", "posts.title", "String", false),
        make_selection("posts.author_name", "posts.writerName", "String", false), // nested alias
    ];

    let result = transform_with_selections(&input, "User", &selections, &registry);

    assert_eq!(result["__typename"], "User");
    assert_eq!(result["userName"], "John");

    let posts = result["posts"].as_array().expect("posts should be array");
    assert_eq!(posts.len(), 1);

    let post = &posts[0];
    assert_eq!(post["__typename"], "Post");
    assert_eq!(post["title"], "My Post");
    assert_eq!(post["writerName"], "Jane Doe"); // ← nested alias applied
    assert!(post.get("authorName").is_none()); // original camelCase not present
}

#[test]
fn test_deep_nesting_with_multiple_aliases() {
    let registry = create_test_schema();

    // Input: User → Posts → Comments (3 levels deep)
    let input = json!({
        "id": "1",
        "user_name": "John",
        "posts": [{
            "id": "10",
            "author_name": "Jane",
            "comments": [{
                "id": "100",
                "comment_text": "Great post!",
                "commenter_name": "Bob"
            }]
        }]
    });

    // Field selections with aliases at multiple levels
    let selections = vec![
        make_selection("id", "id", "String", false),
        make_selection("user_name", "name", "String", false), // alias at root
        make_selection("posts.id", "posts.postId", "String", false), // alias in array
        make_selection("posts.author_name", "posts.writer", "String", false), // alias in array
        make_selection("posts.comments.id", "posts.comments.commentId", "String", false),
        make_selection("posts.comments.comment_text", "posts.comments.text", "String", false), /* deep alias */
        make_selection("posts.comments.commenter_name", "posts.comments.author", "String", false),
    ];

    let result = transform_with_selections(&input, "User", &selections, &registry);

    assert_eq!(result["__typename"], "User");
    assert_eq!(result["name"], "John"); // root alias

    let posts = result["posts"].as_array().unwrap();
    let post = &posts[0];
    assert_eq!(post["postId"], "10"); // array alias
    assert_eq!(post["writer"], "Jane"); // array alias

    let comments = post["comments"].as_array().unwrap();
    let comment = &comments[0];
    assert_eq!(comment["commentId"], "100"); // deep alias
    assert_eq!(comment["text"], "Great post!"); // deep alias
    assert_eq!(comment["author"], "Bob"); // deep alias
}

#[test]
fn test_mix_aliased_and_non_aliased_fields() {
    let registry = create_test_schema();

    // Input: User with some fields aliased, some not
    let input = json!({
        "id": "1",
        "user_name": "John",
        "profile_image": "avatar.jpg"
    });

    // Field selections: Only alias profile_image, others use camelCase
    let selections = vec![
        make_selection("id", "id", "String", false), // no alias (same as field)
        make_selection("user_name", "userName", "String", false), // camelCase (no alias)
        make_selection("profile_image", "avatar", "String", false), // aliased
    ];

    let result = transform_with_selections(&input, "User", &selections, &registry);

    assert_eq!(result["__typename"], "User");
    assert_eq!(result["id"], "1"); // no transformation
    assert_eq!(result["userName"], "John"); // camelCase
    assert_eq!(result["avatar"], "avatar.jpg"); // alias
}

#[test]
fn test_null_values_preserved_with_aliases() {
    let registry = create_test_schema();

    // Input: User with null profile_image
    let input = json!({
        "id": "1",
        "profile_image": null
    });

    let selections = vec![
        make_selection("id", "id", "String", false),
        make_selection("profile_image", "avatar", "String", false),
    ];

    let result = transform_with_selections(&input, "User", &selections, &registry);

    assert_eq!(result["__typename"], "User");
    assert_eq!(result["id"], "1");
    assert_eq!(result["avatar"], Value::Null); // null preserved with alias
}

#[test]
fn test_empty_array_with_aliases() {
    let registry = create_test_schema();

    // Input: User with empty posts array
    let input = json!({
        "id": "1",
        "posts": []
    });

    let selections = vec![
        make_selection("id", "id", "String", false),
        make_selection("posts.id", "posts.postId", "String", false),
    ];

    let result = transform_with_selections(&input, "User", &selections, &registry);

    assert_eq!(result["__typename"], "User");
    assert_eq!(result["id"], "1");
    assert_eq!(result["posts"], json!([])); // empty array preserved
}

#[test]
fn test_alias_materialized_path_decomposition() {
    let registry = create_test_schema();

    // Input: Nested structure to test path decomposition
    let input = json!({
        "posts": [{
            "comments": [{
                "commenter_name": "Alice"
            }]
        }]
    });

    // This tests that we correctly decompose "posts.comments.commenter_name"
    // into: posts → comments → commenter_name, then apply alias at the leaf
    let selections = vec![make_selection(
        "posts.comments.commenter_name",
        "posts.comments.author",
        "String",
        false,
    )];

    let result = transform_with_selections(&input, "User", &selections, &registry);

    let posts = result["posts"].as_array().unwrap();
    let comments = posts[0]["comments"].as_array().unwrap();
    assert_eq!(comments[0]["author"], "Alice"); // alias applied at correct depth
}

#[test]
fn test_multiple_aliases_same_nested_level() {
    let registry = create_test_schema();

    // Input: Multiple fields at same nesting level, each with different alias
    let input = json!({
        "posts": [{
            "id": "1",
            "title": "Post Title",
            "author_name": "John"
        }]
    });

    let selections = vec![
        make_selection("posts.id", "posts.postId", "String", false),
        make_selection("posts.title", "posts.heading", "String", false),
        make_selection("posts.author_name", "posts.writer", "String", false),
    ];

    let result = transform_with_selections(&input, "User", &selections, &registry);

    let post = &result["posts"][0];
    assert_eq!(post["postId"], "1");
    assert_eq!(post["heading"], "Post Title");
    assert_eq!(post["writer"], "John");
}

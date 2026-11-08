//! Field projection: the part of a row the GraphQL query selected
//!
//! A [`Projection`] is a tree with one [`ProjectedField`] per selected field: the
//! field's key in the row JSON, its response key (the alias, or the field name) and,
//! for an object or a list of objects, the projection of its value. A response built
//! from it holds exactly the selected fields: a key is matched by comparing it with
//! the selected keys, so a key that isn't selected is never written. Two aliases of
//! one field are two entries, each with its own sub-selection.

use serde_json::Value;

use crate::{camel_case::to_camel_case, core::camel::snake_to_camel};

/// The field name GraphQL answers with the object's type name
pub const TYPENAME: &str = "__typename";

/// A selected field
#[derive(Debug, Clone, PartialEq)]
pub struct ProjectedField {
    /// The field's key in the row JSON: `first_name`
    pub source: String,
    /// Other spellings of `source` to look for when the JSON hasn't it: `firstName`
    pub alternates: Vec<String>,
    /// The key the field is written under: its alias, or its name
    pub output: String,
    /// The type of the objects in the field's value, when known
    pub type_name: Option<String>,
    /// For an object (or a list of objects), the fields selected on it; `None` for a
    /// leaf, whose value is written as it is
    pub children: Option<Projection>,
}

impl ProjectedField {
    fn new(source: &str, output: &str) -> Self {
        let mut alternates = Vec::new();
        if source != TYPENAME {
            for spelling in [to_camel_case(source), to_snake_case(source)] {
                if spelling != source && !alternates.contains(&spelling) {
                    alternates.push(spelling);
                }
            }
        }
        ProjectedField {
            source: source.to_string(),
            alternates,
            output: output.to_string(),
            type_name: None,
            children: None,
        }
    }

    /// Whether this is the `__typename` meta-field
    #[inline]
    pub fn is_typename(&self) -> bool {
        self.source == TYPENAME
    }

    /// The field's value in a JSON object: under `source`, else an alternate
    /// spelling, else a snake_case key that camelCases like it (`dns_1` for `dns1`)
    pub fn value_in<'v>(&self, map: &'v serde_json::Map<String, Value>) -> Option<&'v Value> {
        map.get(&self.source)
            .or_else(|| self.alternates.iter().find_map(|key| map.get(key)))
            .or_else(|| {
                let camel = to_camel_case(&self.source);
                map.iter()
                    .find(|(key, _)| key.contains('_') && to_camel_case(key) == camel)
                    .map(|(_, value)| value)
            })
    }
}

/// The fields selected on an object, in selection order
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Projection {
    pub fields: Vec<ProjectedField>,
    /// (JSON key, field index) for every spelling of every source, sorted by key: a
    /// key is looked up by binary search, and an exact comparison
    index: Vec<(Box<[u8]>, usize)>,
    /// One bit per hash of the keys in `index`: a key whose bit is clear isn't
    /// selected, without a search. A set bit only says "maybe": `index` decides.
    filter: u128,
}

impl Projection {
    /// Build from field paths alone: `[["id"], ["author", "first_name"]]`.
    ///
    /// Each segment is written under its own name, camelCased when `camel_case`.
    pub fn from_paths(paths: &[Vec<String>], camel_case: bool) -> Self {
        let mut projection = Projection::default();
        for path in paths {
            let outputs: Vec<String> = path
                .iter()
                .map(|segment| {
                    if camel_case && segment != TYPENAME {
                        to_camel_case(segment)
                    } else {
                        segment.clone()
                    }
                })
                .collect();
            let sources: Vec<&str> = path.iter().map(String::as_str).collect();
            projection.insert(&sources, &outputs, None, false);
        }
        projection.finish();
        projection
    }

    /// Build from field selections, as the Python side sends them:
    ///
    /// ```json
    /// {"materialized_path": "author.first_name", "response_path": "writer.firstName",
    ///  "alias": "firstName", "type_name": "String", "is_nested_object": false}
    /// ```
    ///
    /// `materialized_path` gives the JSON keys, `response_path` the response key of
    /// each of its segments. Without `response_path`, a segment is written under the
    /// `alias` of the selection ending there, else its key camelCased. A selection
    /// with `is_nested_object` is an object even when nothing below it is selected.
    pub fn from_selections(selections: &[Value]) -> Self {
        let paths: Vec<&str> = selections
            .iter()
            .filter_map(|s| s.get("materialized_path").and_then(Value::as_str))
            .collect();
        let alias_of = |path: &str| -> Option<&str> {
            selections.iter().find_map(|s| {
                (s.get("materialized_path").and_then(Value::as_str) == Some(path))
                    .then(|| s.get("alias").and_then(Value::as_str))
                    .flatten()
            })
        };

        let mut projection = Projection::default();
        for (selection, path) in selections
            .iter()
            .filter(|s| s.get("materialized_path").and_then(Value::as_str).is_some())
            .zip(paths)
        {
            if path.is_empty() {
                continue;
            }
            let sources: Vec<&str> = path.split('.').collect();
            let given: Option<Vec<String>> = selection
                .get("response_path")
                .and_then(Value::as_str)
                .map(|p| p.split('.').map(str::to_string).collect())
                .filter(|p: &Vec<String>| p.len() == sources.len());
            let outputs = given.unwrap_or_else(|| {
                (0..sources.len())
                    .map(|i| {
                        let prefix = sources[..=i].join(".");
                        alias_of(&prefix)
                            .map(|alias| alias.rsplit('.').next().unwrap_or(alias).to_string())
                            .unwrap_or_else(|| to_camel_case(sources[i]))
                    })
                    .collect()
            });
            let is_object =
                selection.get("is_nested_object").and_then(Value::as_bool).unwrap_or(false);
            let type_name = selection.get("type_name").and_then(Value::as_str);
            projection.insert(&sources, &outputs, type_name, is_object);
        }
        projection.finish();
        projection
    }

    /// Add the path `sources`, written under `outputs`; its last field gets
    /// `type_name`, and is an object when `is_object`
    fn insert(
        &mut self,
        sources: &[&str],
        outputs: &[String],
        type_name: Option<&str>,
        is_object: bool,
    ) {
        let (Some(source), Some(output)) = (sources.first(), outputs.first()) else {
            return;
        };
        let position = match self.fields.iter().position(|f| f.output == *output) {
            Some(position) => position,
            None => {
                self.fields.push(ProjectedField::new(source, output));
                self.fields.len() - 1
            },
        };
        let field = &mut self.fields[position];
        if sources.len() == 1 {
            if let Some(type_name) = type_name {
                if is_object || field.is_typename() {
                    field.type_name = Some(type_name.to_string());
                }
            }
            if is_object && field.children.is_none() {
                field.children = Some(Projection::default());
            }
        } else {
            field.children.get_or_insert_with(Projection::default).insert(
                &sources[1..],
                &outputs[1..],
                type_name,
                is_object,
            );
        }
    }

    /// Build the lookup index, at every level
    fn finish(&mut self) {
        self.index.clear();
        for (i, field) in self.fields.iter_mut().enumerate() {
            self.index.push((field.source.as_bytes().into(), i));
            for alternate in &field.alternates {
                self.index.push((alternate.as_bytes().into(), i));
            }
            if let Some(children) = field.children.as_mut() {
                children.finish();
            }
        }
        self.index.sort();
        self.filter = self.index.iter().fold(0, |filter, (key, _)| filter | key_bit(key));
    }

    /// The indexes of the fields read from the JSON key `key`, in selection order
    /// (one per alias). Exact: a key that isn't one of the selected spellings
    /// matches nothing.
    #[inline]
    pub fn matching(&self, key: &[u8]) -> impl Iterator<Item = usize> + '_ {
        self.entries(key).iter().map(|(_, i)| *i)
    }

    /// Like [`matching`](Self::matching), and a snake_case key nothing matches is
    /// looked up camelCased: `dns_1` is the field `dns1`. `scratch` holds the
    /// camelCased key.
    #[inline]
    pub fn matching_or_camel(
        &self,
        key: &[u8],
        scratch: &mut Vec<u8>,
    ) -> impl Iterator<Item = usize> + '_ {
        let mut entries = self.entries(key);
        if entries.is_empty() && key.contains(&b'_') {
            entries = self.entries(snake_to_camel(key, scratch));
        }
        entries.iter().map(|(_, i)| *i)
    }

    #[inline]
    fn entries(&self, key: &[u8]) -> &[(Box<[u8]>, usize)] {
        if self.filter & key_bit(key) == 0 {
            return &self.index[..0];
        }
        let start = self.index.partition_point(|(k, _)| &**k < key);
        let end = start + self.index[start..].partition_point(|(k, _)| &**k == key);
        &self.index[start..end]
    }

    /// Whether nothing is selected
    pub fn is_empty(&self) -> bool {
        self.fields.is_empty()
    }
}

/// The bit of `key` in a projection's filter (FNV-1a hash, modulo 128)
#[inline(always)]
fn key_bit(key: &[u8]) -> u128 {
    let mut hash: u32 = 2166136261;
    for &byte in key {
        hash ^= byte as u32;
        hash = hash.wrapping_mul(16777619);
    }
    1u128 << (hash % 128)
}

/// `firstName` → `first_name` (ASCII upper case letters only)
fn to_snake_case(s: &str) -> String {
    let mut result = String::with_capacity(s.len() + 4);
    for (i, c) in s.chars().enumerate() {
        if c.is_ascii_uppercase() {
            if i > 0 {
                result.push('_');
            }
            result.push(c.to_ascii_lowercase());
        } else {
            result.push(c);
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    fn paths(list: &[&[&str]]) -> Vec<Vec<String>> {
        list.iter().map(|p| p.iter().map(|s| s.to_string()).collect()).collect()
    }

    fn matches(projection: &Projection, key: &str) -> Vec<String> {
        projection
            .matching(key.as_bytes())
            .map(|i| projection.fields[i].output.clone())
            .collect()
    }

    #[test]
    fn only_selected_keys_match() {
        let projection = Projection::from_paths(&paths(&[&["id"], &["first_name"]]), true);

        assert_eq!(matches(&projection, "id"), ["id"]);
        assert_eq!(matches(&projection, "first_name"), ["firstName"]);
        assert_eq!(matches(&projection, "firstName"), ["firstName"]);
        assert!(matches(&projection, "last_name").is_empty());
        assert!(matches(&projection, "i").is_empty());
        assert!(matches(&projection, "idx").is_empty());
    }

    #[test]
    fn no_key_collides_with_a_selected_one() {
        // A hash bitmap matched any key hashing to a selected key's bit
        let projection = Projection::from_paths(&paths(&[&["author"]]), true);

        for n in 0..10_000 {
            let key = format!("secret_{n}");
            assert!(matches(&projection, &key).is_empty(), "{key} matched");
        }
    }

    #[test]
    fn nested_paths_build_children() {
        let projection = Projection::from_paths(
            &paths(&[&["author", "first_name"], &["author", "id"], &["id"]]),
            false,
        );

        assert_eq!(projection.fields.len(), 2);
        let author = &projection.fields[0];
        assert_eq!(author.output, "author");
        let children = author.children.as_ref().unwrap();
        assert_eq!(matches(children, "first_name"), ["first_name"]);
        assert_eq!(matches(children, "id"), ["id"]);
        assert!(matches(&projection, "first_name").is_empty());
        assert!(projection.fields[1].children.is_none());
    }

    #[test]
    fn response_paths_give_each_segment_its_key() {
        let projection = Projection::from_selections(&[
            json!({"materialized_path": "device", "response_path": "d",
                   "is_nested_object": true, "type_name": "Device"}),
            json!({"materialized_path": "device.id", "response_path": "d.id"}),
            json!({"materialized_path": "device", "response_path": "e",
                   "is_nested_object": true, "type_name": "Device"}),
            json!({"materialized_path": "device.name", "response_path": "e.label"}),
        ]);

        assert_eq!(matches(&projection, "device"), ["d", "e"]);
        let d = projection.fields[0].children.as_ref().unwrap();
        let e = projection.fields[1].children.as_ref().unwrap();
        assert_eq!(matches(d, "id"), ["id"]);
        assert!(matches(d, "name").is_empty());
        assert_eq!(matches(e, "name"), ["label"]);
        assert_eq!(projection.fields[0].type_name.as_deref(), Some("Device"));
    }

    #[test]
    fn without_response_paths_aliases_name_the_segments() {
        let projection = Projection::from_selections(&[
            json!({"materialized_path": "author_info", "alias": "authorInfo",
                   "is_nested_object": true}),
            json!({"materialized_path": "author_info.first_name", "alias": "name"}),
            json!({"materialized_path": "created_at", "alias": "createdAt"}),
        ]);

        assert_eq!(matches(&projection, "author_info"), ["authorInfo"]);
        assert_eq!(matches(&projection, "created_at"), ["createdAt"]);
        let author = projection.fields[0].children.as_ref().unwrap();
        assert_eq!(matches(author, "first_name"), ["name"]);
    }

    #[test]
    fn an_object_with_nothing_but_typename_selected_is_an_object() {
        let projection = Projection::from_selections(&[json!(
            {"materialized_path": "author", "response_path": "author", "is_nested_object": true}
        )]);

        assert_eq!(projection.fields[0].children, Some(Projection::default()));
    }
}

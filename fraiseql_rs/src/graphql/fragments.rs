//! Fragment cycle detection and validation.
//!
//! This module implements GraphQL fragment cycle detection using DFS-based
//! cycle detection with backtracking to identify circular fragment dependencies.

use std::collections::{HashMap, HashSet};

use crate::graphql::types::{FragmentDefinition, ParsedQuery};

/// Fragment dependency graph and cycle detection
pub struct FragmentGraph {
    /// Map of fragment name to set of fragment names it depends on
    dependencies: HashMap<String, HashSet<String>>,
}

impl FragmentGraph {
    /// Create a new fragment graph from parsed query
    pub fn new(query: &ParsedQuery) -> Self {
        let mut dependencies = HashMap::new();

        // Build dependency graph from fragment definitions
        for fragment in &query.fragments {
            let deps = Self::extract_fragment_dependencies(fragment, &query.fragments);
            dependencies.insert(fragment.name.clone(), deps);
        }

        Self { dependencies }
    }

    /// Extract fragment dependencies for a single fragment
    fn extract_fragment_dependencies(
        fragment: &FragmentDefinition,
        all_fragments: &[FragmentDefinition],
    ) -> HashSet<String> {
        let mut deps = HashSet::new();

        // Direct fragment spreads
        deps.extend(fragment.fragment_spreads.iter().cloned());

        // Recursive dependencies through nested selections
        for selection in &fragment.selections {
            Self::extract_selection_dependencies(selection, all_fragments, &mut deps);
        }

        deps
    }

    /// Extract dependencies from field selections (recursive helper)
    fn extract_selection_dependencies(
        selection: &crate::graphql::types::FieldSelection,
        _all_fragments: &[FragmentDefinition],
        _deps: &mut HashSet<String>,
    ) {
        // Fragment spreads are already collected during parsing in
        // FragmentDefinition.fragment_spreads No additional processing needed here for
        // selection-level dependencies

        // Recursively check nested selections
        for nested in &selection.nested_fields {
            Self::extract_selection_dependencies(nested, _all_fragments, _deps);
        }
    }

    /// Detect cycles in fragment dependencies using DFS
    ///
    /// Returns Ok(()) if no cycles found, Err(cycle_path) if cycle detected
    pub fn detect_cycles(&self) -> Result<(), Vec<String>> {
        let mut visited = HashSet::new();
        let mut recursion_stack = HashSet::new();
        let mut cycle_path = Vec::new();

        for fragment_name in self.dependencies.keys() {
            if !visited.contains(fragment_name) {
                if let Some(cycle) = self.dfs_cycle_detect(
                    fragment_name,
                    &mut visited,
                    &mut recursion_stack,
                    &mut cycle_path,
                ) {
                    return Err(cycle);
                }
            }
        }

        Ok(())
    }

    /// DFS cycle detection helper
    fn dfs_cycle_detect(
        &self,
        fragment_name: &str,
        visited: &mut HashSet<String>,
        recursion_stack: &mut HashSet<String>,
        cycle_path: &mut Vec<String>,
    ) -> Option<Vec<String>> {
        visited.insert(fragment_name.to_string());
        recursion_stack.insert(fragment_name.to_string());
        cycle_path.push(fragment_name.to_string());

        if let Some(deps) = self.dependencies.get(fragment_name) {
            for dep in deps {
                if let Some(cycle) =
                    self.check_dependency_cycle(dep, visited, recursion_stack, cycle_path)
                {
                    return Some(cycle);
                }
            }
        }

        recursion_stack.remove(fragment_name);
        cycle_path.pop();
        None
    }

    /// Check if a dependency creates a cycle (helper to reduce nesting)
    fn check_dependency_cycle(
        &self,
        dep: &str,
        visited: &mut HashSet<String>,
        recursion_stack: &mut HashSet<String>,
        cycle_path: &mut Vec<String>,
    ) -> Option<Vec<String>> {
        if !visited.contains(dep) {
            // Not visited yet - recurse
            return self.dfs_cycle_detect(dep, visited, recursion_stack, cycle_path);
        }

        if recursion_stack.contains(dep) {
            // Cycle found - extract cycle path
            let cycle_start = cycle_path.iter().position(|f| f == dep).unwrap();
            let cycle = cycle_path[cycle_start..].to_vec();
            return Some(cycle);
        }

        None
    }

    /// Validate all fragments in the query
    pub fn validate_fragments(&self) -> Result<(), String> {
        self.detect_cycles()
            .map_err(|cycle| format!("Fragment cycle detected: {}", cycle.join(" -> ")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_no_cycles() {
        let graph = FragmentGraph {
            dependencies: HashMap::from([
                ("FragA".to_string(), HashSet::from(["FragB".to_string()])),
                ("FragB".to_string(), HashSet::from(["FragC".to_string()])),
                ("FragC".to_string(), HashSet::new()),
            ]),
        };
        assert!(graph.detect_cycles().is_ok());
    }

    #[test]
    fn test_simple_cycle() {
        let graph = FragmentGraph {
            dependencies: HashMap::from([
                ("FragA".to_string(), HashSet::from(["FragB".to_string()])),
                ("FragB".to_string(), HashSet::from(["FragA".to_string()])),
            ]),
        };
        let result = graph.detect_cycles();
        assert!(result.is_err());
        let cycle = result.unwrap_err();
        assert_eq!(cycle, vec!["FragA", "FragB", "FragA"]);
    }

    #[test]
    fn test_complex_cycle() {
        let graph = FragmentGraph {
            dependencies: HashMap::from([
                ("FragA".to_string(), HashSet::from(["FragB".to_string()])),
                ("FragB".to_string(), HashSet::from(["FragC".to_string()])),
                ("FragC".to_string(), HashSet::from(["FragA".to_string()])),
                ("FragD".to_string(), HashSet::from(["FragE".to_string()])),
                ("FragE".to_string(), HashSet::new()),
            ]),
        };
        let result = graph.detect_cycles();
        assert!(result.is_err());
        let cycle = result.unwrap_err();
        assert_eq!(cycle, vec!["FragA", "FragB", "FragC", "FragA"]);
    }

    #[test]
    fn test_multiple_cycles() {
        let graph = FragmentGraph {
            dependencies: HashMap::from([
                ("FragA".to_string(), HashSet::from(["FragB".to_string()])),
                ("FragB".to_string(), HashSet::from(["FragA".to_string()])),
                ("FragC".to_string(), HashSet::from(["FragD".to_string()])),
                ("FragD".to_string(), HashSet::from(["FragC".to_string()])),
            ]),
        };
        let result = graph.detect_cycles();
        assert!(result.is_err());
        // Should detect one of the cycles (DFS order dependent)
        let cycle = result.unwrap_err();
        assert!(cycle.len() >= 3); // At least A->B->A
    }

    #[test]
    fn test_self_reference_cycle() {
        let graph = FragmentGraph {
            dependencies: HashMap::from([(
                "FragA".to_string(),
                HashSet::from(["FragA".to_string()]),
            )]),
        };
        let result = graph.detect_cycles();
        assert!(result.is_err());
        let cycle = result.unwrap_err();
        assert_eq!(cycle, vec!["FragA", "FragA"]);
    }
}

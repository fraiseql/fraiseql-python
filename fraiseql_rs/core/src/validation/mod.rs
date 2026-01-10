//! Input validation module.
//!
//! Provides ID policy validation and GraphQL input processing.

mod id_policy;
mod input_processor;

pub use id_policy::{validate_id, IDPolicy, IDValidationError};
pub use input_processor::{process_variables, InputProcessingConfig, ProcessingError};

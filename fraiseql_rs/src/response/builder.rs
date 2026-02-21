//! Response builder for GraphQL responses.

use serde_json::Value;

use crate::response::{ChunkedWriter, ResponseStream, transform_row_keys};

/// Builder for GraphQL responses with streaming support
pub struct ResponseBuilder {
    chunk_size: usize,
}

impl ResponseBuilder {
    pub fn new() -> Self {
        ResponseBuilder {
            chunk_size: 8192, // 8KB chunks
        }
    }

    pub fn with_chunk_size(mut self, size: usize) -> Self {
        self.chunk_size = size;
        self
    }

    /// Build a complete response from all rows (for small result sets)
    pub fn build_response(&self, rows: &[Value]) -> Result<String, serde_json::Error> {
        let mut transformed_rows = Vec::with_capacity(rows.len());
        for row in rows {
            transformed_rows.push(transform_row_keys(row));
        }

        let response = serde_json::json!({
            "data": {
                "items": transformed_rows
            }
        });

        serde_json::to_string(&response)
    }

    /// Build a streaming response (for large result sets)
    pub fn build_streaming_response<W: std::io::Write>(
        &self,
        rows: &[Value],
        writer: W,
    ) -> std::io::Result<()> {
        let mut stream = ResponseStream::new(writer);
        stream.start()?;

        for row in rows {
            let transformed = transform_row_keys(row);
            stream.write_row(&transformed)?;
        }

        stream.finish()
    }

    /// Create a chunked writer for streaming
    pub fn create_chunked_writer(&self) -> ChunkedWriter {
        ChunkedWriter::new(self.chunk_size)
    }
}

impl Default for ResponseBuilder {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn test_build_response() {
        let builder = ResponseBuilder::new();
        let rows = vec![
            json!({"user_id": 1, "first_name": "Alice"}),
            json!({"user_id": 2, "first_name": "Bob"}),
        ];

        let response = builder.build_response(&rows).unwrap();
        let expected = r#"{"data":{"items":[{"userId":1,"firstName":"Alice"},{"userId":2,"firstName":"Bob"}]}}"#;
        assert_eq!(response, expected);
    }

    #[test]
    fn test_build_streaming_response() {
        let builder = ResponseBuilder::new();
        let rows = vec![
            json!({"user_id": 1, "first_name": "Alice"}),
            json!({"user_id": 2, "first_name": "Bob"}),
        ];

        let mut buffer = Vec::new();
        builder.build_streaming_response(&rows, &mut buffer).unwrap();

        let result = String::from_utf8(buffer).unwrap();
        let expected = r#"{"data":{"items":[{"userId":1,"firstName":"Alice"},{"userId":2,"firstName":"Bob"}]}}"#;
        assert_eq!(result, expected);
    }

    #[test]
    fn test_chunked_writer_creation() {
        let builder = ResponseBuilder::new().with_chunk_size(4096);
        let writer = builder.create_chunked_writer();
        assert_eq!(writer.total_written(), 0);
    }
}

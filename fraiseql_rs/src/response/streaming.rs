//! Zero-copy streaming response builder.

use std::io::Write;

use serde_json::Value;

/// Stream rows directly to response buffer without full buffering.
pub struct ResponseStream<W: Write> {
    writer:    W,
    row_count: usize,
    started:   bool,
}

impl<W: Write> ResponseStream<W> {
    pub fn new(writer: W) -> Self {
        ResponseStream {
            writer,
            row_count: 0,
            started: false,
        }
    }

    /// Start the GraphQL response array
    pub fn start(&mut self) -> std::io::Result<()> {
        if !self.started {
            // Write opening of GraphQL response
            self.writer.write_all(b"{\"data\":{\"items\":[")?;
            self.started = true;
        }
        Ok(())
    }

    /// Write a single row (automatically formatted as JSON)
    pub fn write_row(&mut self, row: &Value) -> std::io::Result<()> {
        if self.row_count > 0 {
            self.writer.write_all(b",")?; // Comma separator
        }

        // Write row as compact JSON directly to writer (zero-copy)
        serde_json::to_writer(&mut self.writer, row)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;

        self.row_count += 1;
        Ok(())
    }

    /// Finish the response
    pub fn finish(&mut self) -> std::io::Result<()> {
        self.writer.write_all(b"]}}")?; // Close array and response
        self.writer.flush()?;
        Ok(())
    }

    pub fn row_count(&self) -> usize {
        self.row_count
    }
}

/// Memory-efficient buffered writer with configurable chunk size.
pub struct ChunkedWriter {
    buffer:        Vec<u8>,
    chunk_size:    usize,
    total_written: usize,
}

impl ChunkedWriter {
    pub fn new(chunk_size: usize) -> Self {
        ChunkedWriter {
            buffer: Vec::with_capacity(chunk_size),
            chunk_size,
            total_written: 0,
        }
    }

    pub fn should_flush(&self) -> bool {
        self.buffer.len() >= self.chunk_size
    }

    pub fn get_chunk(&mut self) -> Option<Vec<u8>> {
        if self.buffer.is_empty() {
            return None;
        }
        Some(std::mem::replace(&mut self.buffer, Vec::with_capacity(self.chunk_size)))
    }

    pub fn total_written(&self) -> usize {
        self.total_written
    }
}

impl Write for ChunkedWriter {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        self.buffer.extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        // For ChunkedWriter, flush() doesn't actually write anywhere
        // Consumers should call get_chunk() to retrieve buffered data
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn test_response_stream_basic() {
        let mut buffer = Vec::new();
        {
            let mut stream = ResponseStream::new(&mut buffer);

            // Start response
            stream.start().unwrap();

            // Add rows
            let row1 = json!({"id": 1, "name": "Alice"});
            let row2 = json!({"id": 2, "name": "Bob"});

            stream.write_row(&row1).unwrap();
            stream.write_row(&row2).unwrap();

            // Finish
            stream.finish().unwrap();

            assert_eq!(stream.row_count(), 2);
        }

        let result = String::from_utf8(buffer).unwrap();
        assert_eq!(result, r#"{"data":{"items":[{"id":1,"name":"Alice"},{"id":2,"name":"Bob"}]}}"#);
    }

    #[test]
    fn test_response_stream_empty() {
        let mut buffer = Vec::new();
        {
            let mut stream = ResponseStream::new(&mut buffer);

            stream.start().unwrap();
            stream.finish().unwrap();

            assert_eq!(stream.row_count(), 0);
        }

        let result = String::from_utf8(buffer).unwrap();
        assert_eq!(result, r#"{"data":{"items":[]}}"#);
    }

    #[test]
    fn test_chunked_writer() {
        let mut writer = ChunkedWriter::new(10);

        // Write small amount
        writer.write_all(b"hello").unwrap();
        assert!(!writer.should_flush());

        // Write more to exceed chunk size
        writer.write_all(b" world!!!").unwrap();
        assert!(writer.should_flush());

        // Get chunk
        let chunk = writer.get_chunk().unwrap();
        assert_eq!(String::from_utf8(chunk).unwrap(), "hello world!!!");

        // Verify state
        assert_eq!(writer.total_written(), 13);
        assert!(!writer.should_flush());
    }

    #[test]
    fn test_chunked_writer_empty() {
        let mut writer = ChunkedWriter::new(10);
        assert!(writer.get_chunk().is_none());
        assert_eq!(writer.total_written(), 0);
    }
}

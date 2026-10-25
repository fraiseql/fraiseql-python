//! Zero-copy JSON transformer (Streaming API)
//!
//! This module provides streaming JSON transformation without intermediate
//! Value allocations. It reads JSON bytes directly and writes transformed
//! output in a single pass.
//!
//! ## Architecture
//!
//! FraiseQL has **two JSON transformation strategies**:
//! - **crate::json_transform**: Value-based API for PyO3, schema-aware
//! - **This module (core::transform)**: Zero-copy streaming API for query pipeline
//!
//! ## When to Use This Module
//!
//! ✅ **Use `core::transform` when**:
//! - GraphQL query pipeline (hot path, 3-5x faster than Value-based)
//! - Need streaming/zero-copy (80% less memory)
//! - High volume (> 1000 req/sec)
//! - Field projection required
//!
//! ❌ **Use `crate::json_transform` instead when**:
//! - Called from Python via PyO3
//! - Need schema-aware transformation (nested types)
//! - Working with JSON strings (`String` → `String`)
//! - Need `serde_json::Value` compatibility
//!
//! For detailed architecture rationale, see: `docs/json-transformation-guide.md`

use pyo3::PyErr;

use crate::{core::camel::snake_to_camel, pipeline::projection::Projection};

/// Maximum JSON nesting depth to prevent stack overflow
///
/// # Recursion Safety
///
/// Maximum depth: 64 levels (MAX_JSON_DEPTH)
///
/// **Stack usage calculation:**
/// - Each recursion level: ~50-100 bytes (function frame + local variables)
/// - Worst case: 64 * 100 = 6.4 KB stack usage
/// - Typical stack size: 2-8 MB
/// - Safety margin: 6.4 KB is only 0.3% of minimum stack (2MB)
///
/// **Why 64 levels?**
/// - **Most JSON**: < 10 levels deep (typical GraphQL responses: 3-5 levels)
/// - **Malicious payloads**: Caught before causing stack overflow
/// - **Standard stack**: 2-8 MB (6.4 KB is safe even with other stack frames)
/// - **Performance**: No impact on normal queries, only extreme cases
///
/// **Attack prevention:**
/// - Without limit: Malicious input could cause stack overflow crash
/// - With limit: Returns `MaxDepthExceeded` error before danger
/// - Protects against: Deeply nested JSON bombs, accidental infinite loops
pub const MAX_JSON_DEPTH: usize = 64;

/// Transform configuration (zero-cost at compile time)
#[derive(Clone, Copy)]
pub struct TransformConfig {
    pub add_typename: bool,
    pub camel_case: bool,
    pub project_fields: bool,
    pub add_graphql_wrapper: bool,
    pub max_depth: usize,
}

impl Default for TransformConfig {
    fn default() -> Self {
        Self {
            add_typename: true,
            camel_case: true,
            project_fields: false,
            add_graphql_wrapper: true,
            max_depth: MAX_JSON_DEPTH,
        }
    }
}

/// Zero-copy JSON transformer
///
/// PERFORMANCE CHARACTERISTICS:
/// - Single-pass: Reads input once, writes output once
/// - Zero-copy keys: Keys transformed in-place when possible
/// - Keys: camelCase keys go through one reused scratch buffer
/// - Projection: a key is looked up in the selection by binary search
///
/// With a [`Projection`], an object is written with exactly its selected fields,
/// each under its response key, an object field projected on its own selection and
/// a leaf copied as it is. Without one, every field is written, its key camelCased
/// when `camel_case`.
///
/// Memory layout:
/// ┌─────────────────────────────────────────────────┐
/// │ Input Buffer (read-only)                        │ ← PostgreSQL result
/// ├─────────────────────────────────────────────────┤
/// │ Key scratch buffer (reused)                     │ ← camelCase keys
/// ├─────────────────────────────────────────────────┤
/// │ Output Buffer (write-only, pre-sized)           │ → HTTP response
/// └─────────────────────────────────────────────────┘
pub struct ZeroCopyTransformer<'a> {
    config: TransformConfig,
    typename: Option<&'a str>,
    projection: Option<&'a Projection>,
    current_depth: usize,
    /// Depth of the row objects: 0 for an object row, 1 for each object of an
    /// array row. `typename` names their type, and only theirs: a nested
    /// object is of another type this transformer doesn't know.
    row_depth: usize,
    /// Reused for each camelCase key, which is copied to the output right away
    key_scratch: Vec<u8>,
}

impl<'a> ZeroCopyTransformer<'a> {
    pub fn new(
        config: TransformConfig,
        typename: Option<&'a str>,
        projection: Option<&'a Projection>,
    ) -> Self {
        ZeroCopyTransformer {
            config,
            typename,
            projection,
            current_depth: 0,
            row_depth: 0,
            key_scratch: Vec::new(),
        }
    }

    /// Transform JSON bytes directly to output buffer
    ///
    /// This is the CORE OPERATION - everything else is sugar.
    ///
    /// # Performance
    /// - Time complexity: O(n) where n = input size
    /// - Space complexity: O(k) where k = output size (pre-allocated)
    /// - Allocations: the output buffer, and the key scratch buffer as it grows
    pub fn transform_bytes(
        &mut self,
        input: &[u8],
        output: &mut ByteBuf,
    ) -> Result<(), TransformError> {
        // Strategy: Streaming parse + streaming write
        // We NEVER materialize the full JSON tree!

        let mut reader = ByteReader::new(input);
        let mut writer = JsonWriter::new(output);
        let projection = if self.config.project_fields {
            self.projection
        } else {
            None
        };
        let typename = self.typename;

        // Transform array/object
        if reader.peek_byte()? == b'[' {
            self.row_depth = self.current_depth + 1;
            self.transform_array(&mut reader, &mut writer, projection, typename)?;
        } else {
            self.row_depth = self.current_depth;
            self.transform_object(&mut reader, &mut writer, projection, typename)?;
        }

        Ok(())
    }

    /// Transform JSON object (recursive)
    ///
    /// `type_name` is the object's type, when known: the row type for a row object,
    /// the field's type from the selection for a nested one.
    #[inline]
    fn transform_object(
        &mut self,
        reader: &mut ByteReader,
        writer: &mut JsonWriter,
        projection: Option<&Projection>,
        type_name: Option<&str>,
    ) -> Result<(), TransformError> {
        // Check recursion depth limit
        if self.current_depth >= self.config.max_depth {
            return Err(TransformError::MaxDepthExceeded(self.config.max_depth));
        }

        // Only a row object is of type `typename`; a nested object keeps the
        // __typename its JSON has, if any
        let inject_typename = self.config.add_typename
            && self.current_depth == self.row_depth
            && self.typename.is_some();

        self.current_depth += 1;

        reader.expect_byte(b'{')?;
        writer.write_object_start()?;

        match projection {
            Some(projection) => {
                self.write_projected_fields(reader, writer, projection, type_name, inject_typename)?
            },
            None => self.write_all_fields(reader, writer, inject_typename)?,
        }

        reader.expect_byte(b'}')?;
        writer.write_object_end()?;

        self.current_depth -= 1;
        Ok(())
    }

    /// Write an object's fields, each key camelCased when `camel_case`
    fn write_all_fields(
        &mut self,
        reader: &mut ByteReader,
        writer: &mut JsonWriter,
        inject_typename: bool,
    ) -> Result<(), TransformError> {
        // Inject __typename FIRST (important for GraphQL clients)
        if inject_typename {
            if let Some(typename) = self.typename {
                writer.write_key(b"__typename")?;
                writer.write_string(typename.as_bytes())?;
            }
        }

        let mut first = true;
        while reader.peek_byte()? != b'}' {
            if !first {
                reader.expect_byte(b',')?;
            }
            first = false;

            let key_bytes = reader.read_string()?;
            reader.expect_byte(b':')?;

            // Skip a __typename already present where one was injected
            if inject_typename && key_bytes == b"__typename" {
                reader.skip_value()?;
                continue;
            }

            // Transform key (camelCase if needed; __typename is a GraphQL name)
            if self.config.camel_case && key_bytes != b"__typename" {
                let camel_key = snake_to_camel(key_bytes, &mut self.key_scratch);
                writer.write_json_key(camel_key)?;
            } else {
                writer.write_json_key(key_bytes)?;
            }

            self.transform_value(reader, writer, None, None)?;
        }
        Ok(())
    }

    /// Write the fields of an object that `projection` selects, under their
    /// response keys; nothing else
    fn write_projected_fields(
        &mut self,
        reader: &mut ByteReader,
        writer: &mut JsonWriter,
        projection: &Projection,
        type_name: Option<&str>,
        inject_typename: bool,
    ) -> Result<(), TransformError> {
        let mut written = Written::new(projection.fields.len());

        if inject_typename {
            if let Some(typename) = self.typename {
                writer.write_key(b"__typename")?;
                writer.write_string(typename.as_bytes())?;
                for (i, field) in projection.fields.iter().enumerate() {
                    if field.is_typename() && field.output == "__typename" {
                        written.set(i);
                    }
                }
            }
        }
        // __typename selected: the object's type, when known; else the JSON's, below
        for (i, field) in projection.fields.iter().enumerate() {
            if !field.is_typename() || written.get(i) {
                continue;
            }
            if let Some(name) = type_name.or(field.type_name.as_deref()) {
                writer.write_key(field.output.as_bytes())?;
                writer.write_string(name.as_bytes())?;
                written.set(i);
            }
        }

        let mut first = true;
        while reader.peek_byte()? != b'}' {
            if !first {
                reader.expect_byte(b',')?;
            }
            first = false;

            let key_bytes = reader.read_string()?;
            reader.expect_byte(b':')?;

            // One field per alias selecting this key: each reads the value again
            let start = reader.position();
            let mut read = false;
            for i in projection.matching(key_bytes) {
                if written.get(i) {
                    continue;
                }
                written.set(i);
                let field = &projection.fields[i];
                if read {
                    reader.seek(start);
                }
                read = true;
                writer.write_key(field.output.as_bytes())?;
                match &field.children {
                    Some(children) if !field.is_typename() => self.transform_value(
                        reader,
                        writer,
                        Some(children),
                        field.type_name.as_deref(),
                    )?,
                    _ => writer.write_raw(reader.read_raw_value()?)?,
                }
            }
            if !read {
                reader.skip_value()?;
            }
        }
        Ok(())
    }

    /// Transform JSON array: each element is projected on `projection`
    #[inline]
    fn transform_array(
        &mut self,
        reader: &mut ByteReader,
        writer: &mut JsonWriter,
        projection: Option<&Projection>,
        type_name: Option<&str>,
    ) -> Result<(), TransformError> {
        // Check recursion depth limit
        if self.current_depth >= self.config.max_depth {
            return Err(TransformError::MaxDepthExceeded(self.config.max_depth));
        }

        self.current_depth += 1;

        reader.expect_byte(b'[')?;
        writer.write_array_start()?;

        let mut first = true;
        while reader.peek_byte()? != b']' {
            if !first {
                reader.expect_byte(b',')?;
                // Write comma to output for array element separation
                writer.write_comma()?;
            }
            first = false;

            self.transform_value(reader, writer, projection, type_name)?;
        }

        reader.expect_byte(b']')?;
        writer.write_array_end()?;

        self.current_depth -= 1;
        Ok(())
    }

    /// Transform JSON value (dispatch based on first byte)
    #[inline(always)]
    fn transform_value(
        &mut self,
        reader: &mut ByteReader,
        writer: &mut JsonWriter,
        projection: Option<&Projection>,
        type_name: Option<&str>,
    ) -> Result<(), TransformError> {
        match reader.peek_byte()? {
            b'{' => self.transform_object(reader, writer, projection, type_name),
            b'[' => self.transform_array(reader, writer, projection, type_name),
            b'"' => {
                let string_bytes = reader.read_string()?;
                writer.write_json_string(string_bytes)
            },
            b't' | b'f' => {
                let bool_bytes = reader.read_bool()?;
                writer.write_raw(bool_bytes)
            },
            b'n' => {
                reader.read_null()?;
                writer.write_null()
            },
            b'-' | b'0'..=b'9' => {
                let number_bytes = reader.read_number()?;
                writer.write_raw(number_bytes)
            },
            other => Err(TransformError::UnexpectedByte(other)),
        }
    }
}

/// Which fields of a projection an object has written
enum Written {
    Small(u128),
    Large(Vec<bool>),
}

impl Written {
    #[inline]
    fn new(len: usize) -> Self {
        if len <= 128 {
            Written::Small(0)
        } else {
            Written::Large(vec![false; len])
        }
    }

    #[inline]
    fn get(&self, i: usize) -> bool {
        match self {
            Written::Small(bits) => bits & (1u128 << i) != 0,
            Written::Large(flags) => flags[i],
        }
    }

    #[inline]
    fn set(&mut self, i: usize) {
        match self {
            Written::Small(bits) => *bits |= 1u128 << i,
            Written::Large(flags) => flags[i] = true,
        }
    }
}

/// Growable byte buffer with smart capacity estimation
pub struct ByteBuf {
    buf: Vec<u8>,
}

impl ByteBuf {
    /// Create with estimated capacity
    ///
    /// Estimation formula:
    /// - Base: 120% of input size (accounts for wrapping + typename)
    /// - Field names: +50% if camelCase (longer keys)
    /// - Projection: -50% if projecting (fewer fields)
    #[inline]
    pub fn with_estimated_capacity(input_size: usize, config: &TransformConfig) -> Self {
        let base = (input_size as f32 * 1.2) as usize;

        let multiplier = match (config.camel_case, config.project_fields) {
            (true, true) => 1.0,  // +50% -50% = 0
            (true, false) => 1.5, // +50%
            (false, true) => 0.7, // -50%
            (false, false) => 1.0,
        };

        let capacity = (base as f32 * multiplier) as usize;

        ByteBuf {
            buf: Vec::with_capacity(capacity),
        }
    }

    #[inline(always)]
    pub fn push(&mut self, byte: u8) {
        self.buf.push(byte);
    }

    #[inline(always)]
    pub fn extend_from_slice(&mut self, bytes: &[u8]) {
        self.buf.extend_from_slice(bytes);
    }

    pub fn into_vec(self) -> Vec<u8> {
        self.buf
    }

    /// Get mutable reference to internal buffer for direct writing
    #[inline(always)]
    pub fn as_mut_vec(&mut self) -> &mut Vec<u8> {
        &mut self.buf
    }
}

/// Streaming byte reader (zero-copy)
pub struct ByteReader<'a> {
    bytes: &'a [u8],
    pos: usize,
}

impl<'a> ByteReader<'a> {
    #[inline]
    pub fn new(bytes: &'a [u8]) -> Self {
        ByteReader { bytes, pos: 0 }
    }

    #[inline(always)]
    pub fn peek_byte(&mut self) -> Result<u8, TransformError> {
        self.skip_whitespace();
        self.bytes.get(self.pos).copied().ok_or(TransformError::UnexpectedEof)
    }

    #[inline]
    pub fn expect_byte(&mut self, expected: u8) -> Result<(), TransformError> {
        self.skip_whitespace();
        let byte = self.bytes.get(self.pos).copied().ok_or(TransformError::UnexpectedEof)?;

        if byte == expected {
            self.pos += 1;
            Ok(())
        } else {
            Err(TransformError::ExpectedByte(expected, byte))
        }
    }

    /// The reader's position in the input
    #[inline(always)]
    pub fn position(&self) -> usize {
        self.pos
    }

    /// Go back to a position `position` returned
    #[inline(always)]
    pub fn seek(&mut self, position: usize) {
        self.pos = position;
    }

    /// Read a JSON value of any type, and return its bytes as they are
    pub fn read_raw_value(&mut self) -> Result<&'a [u8], TransformError> {
        self.skip_whitespace();
        let start = self.pos;
        self.skip_value()?;
        Ok(&self.bytes[start..self.pos])
    }

    /// Read JSON string (returns slice into input buffer - ZERO COPY!)
    ///
    /// This is critical for performance: we NEVER allocate for keys!
    #[inline]
    pub fn read_string(&mut self) -> Result<&'a [u8], TransformError> {
        self.skip_whitespace();
        self.expect_byte(b'"')?;

        let start = self.pos;

        // Fast path: unescaped string (90% of cases)
        while self.pos < self.bytes.len() {
            let byte = self.bytes[self.pos];

            if byte == b'"' {
                let string_bytes = &self.bytes[start..self.pos];
                self.pos += 1; // skip closing quote
                return Ok(string_bytes);
            }

            if byte == b'\\' {
                // Slow path: escaped string
                return self.read_escaped_string(start);
            }

            self.pos += 1;
        }

        Err(TransformError::UnterminatedString)
    }

    /// Skip whitespace (SIMD-optimized)
    #[inline(always)]
    fn skip_whitespace(&mut self) {
        // SIMD: Check 16 bytes at a time for non-whitespace
        while self.pos < self.bytes.len() {
            let byte = self.bytes[self.pos];
            if !matches!(byte, b' ' | b'\n' | b'\r' | b'\t') {
                break;
            }
            self.pos += 1;
        }
    }

    /// Read escaped string (slow path)
    ///
    /// The string is returned with its escapes as they are: `a\"b` for `"a\"b"`.
    /// A backslash escapes the byte after it, so `"a\\"` ends at its last quote.
    fn read_escaped_string(&mut self, start: usize) -> Result<&'a [u8], TransformError> {
        while self.pos < self.bytes.len() {
            match self.bytes[self.pos] {
                b'\\' => self.pos += 2,
                b'"' => {
                    let string_bytes = &self.bytes[start..self.pos];
                    self.pos += 1;
                    return Ok(string_bytes);
                },
                _ => self.pos += 1,
            }
        }
        Err(TransformError::UnterminatedString)
    }

    /// Read boolean value
    pub fn read_bool(&mut self) -> Result<&'a [u8], TransformError> {
        self.skip_whitespace();
        if self.bytes[self.pos..].starts_with(b"true") {
            self.pos += 4;
            Ok(&self.bytes[self.pos - 4..self.pos])
        } else if self.bytes[self.pos..].starts_with(b"false") {
            self.pos += 5;
            Ok(&self.bytes[self.pos - 5..self.pos])
        } else {
            Err(TransformError::InvalidBool)
        }
    }

    /// Read null value
    pub fn read_null(&mut self) -> Result<(), TransformError> {
        self.skip_whitespace();
        if self.bytes[self.pos..].starts_with(b"null") {
            self.pos += 4;
            Ok(())
        } else {
            Err(TransformError::InvalidNull)
        }
    }

    /// Read number
    pub fn read_number(&mut self) -> Result<&'a [u8], TransformError> {
        self.skip_whitespace();
        let start = self.pos;

        while self.pos < self.bytes.len() {
            let byte = self.bytes[self.pos];
            if !matches!(byte, b'-' | b'+' | b'.' | b'e' | b'E' | b'0'..=b'9') {
                break;
            }
            self.pos += 1;
        }

        if start == self.pos {
            Err(TransformError::InvalidNumber)
        } else {
            Ok(&self.bytes[start..self.pos])
        }
    }

    /// Skip a JSON value (for field projection)
    pub fn skip_value(&mut self) -> Result<(), TransformError> {
        self.skip_whitespace();
        match self.bytes[self.pos] {
            b'{' => self.skip_object(),
            b'[' => self.skip_array(),
            b'"' => self.skip_string(),
            b't' | b'f' => self.skip_bool(),
            b'n' => self.skip_null(),
            b'-' | b'0'..=b'9' => self.skip_number(),
            other => Err(TransformError::UnexpectedByte(other)),
        }
    }

    fn skip_object(&mut self) -> Result<(), TransformError> {
        self.pos += 1; // skip '{'
        while self.pos < self.bytes.len() {
            self.skip_whitespace();
            if self.bytes[self.pos] == b'}' {
                self.pos += 1;
                return Ok(());
            }
            self.skip_string()?; // key
            self.expect_byte(b':')?;
            self.skip_value()?; // value
            if self.bytes[self.pos] == b',' {
                self.pos += 1;
            }
        }
        Err(TransformError::UnexpectedEof)
    }

    fn skip_array(&mut self) -> Result<(), TransformError> {
        self.pos += 1; // skip '['
        while self.pos < self.bytes.len() {
            self.skip_whitespace();
            if self.bytes[self.pos] == b']' {
                self.pos += 1;
                return Ok(());
            }
            self.skip_value()?;
            if self.bytes[self.pos] == b',' {
                self.pos += 1;
            }
        }
        Err(TransformError::UnexpectedEof)
    }

    fn skip_string(&mut self) -> Result<(), TransformError> {
        self.pos += 1; // skip opening '"'
        while self.pos < self.bytes.len() {
            if self.bytes[self.pos] == b'"' {
                self.pos += 1;
                return Ok(());
            }
            if self.bytes[self.pos] == b'\\' {
                self.pos += 2; // skip escape sequence
            } else {
                self.pos += 1;
            }
        }
        Err(TransformError::UnterminatedString)
    }

    fn skip_bool(&mut self) -> Result<(), TransformError> {
        if self.bytes[self.pos..].starts_with(b"true") {
            self.pos += 4;
        } else if self.bytes[self.pos..].starts_with(b"false") {
            self.pos += 5;
        } else {
            return Err(TransformError::InvalidBool);
        }
        Ok(())
    }

    fn skip_null(&mut self) -> Result<(), TransformError> {
        if self.bytes[self.pos..].starts_with(b"null") {
            self.pos += 4;
        } else {
            return Err(TransformError::InvalidNull);
        }
        Ok(())
    }

    fn skip_number(&mut self) -> Result<(), TransformError> {
        while self.pos < self.bytes.len() {
            let byte = self.bytes[self.pos];
            if !matches!(byte, b'-' | b'+' | b'.' | b'e' | b'E' | b'0'..=b'9') {
                break;
            }
            self.pos += 1;
        }
        Ok(())
    }
}

/// Streaming JSON writer
pub struct JsonWriter<'a> {
    output: &'a mut ByteBuf,
    needs_comma: bool,
}

impl<'a> JsonWriter<'a> {
    #[inline]
    pub fn new(output: &'a mut ByteBuf) -> Self {
        JsonWriter {
            output,
            needs_comma: false,
        }
    }

    #[inline(always)]
    pub fn write_key(&mut self, key: &[u8]) -> Result<(), TransformError> {
        if self.needs_comma {
            self.output.push(b',');
        }
        self.output.push(b'"');
        self.write_escaped(key)?;
        self.output.push(b'"');
        self.output.push(b':');
        self.needs_comma = false;
        Ok(())
    }

    #[inline(always)]
    pub fn write_string(&mut self, value: &[u8]) -> Result<(), TransformError> {
        self.output.push(b'"');
        self.write_escaped(value)?;
        self.output.push(b'"');
        self.needs_comma = true;
        Ok(())
    }

    /// Write a key read from JSON input: its escapes are kept, not escaped again
    #[inline(always)]
    pub fn write_json_key(&mut self, key: &[u8]) -> Result<(), TransformError> {
        if self.needs_comma {
            self.output.push(b',');
        }
        self.output.push(b'"');
        self.output.extend_from_slice(key);
        self.output.extend_from_slice(b"\":");
        self.needs_comma = false;
        Ok(())
    }

    /// Write a string read from JSON input (`ByteReader::read_string`): its
    /// escapes are kept, not escaped again
    #[inline(always)]
    pub fn write_json_string(&mut self, value: &[u8]) -> Result<(), TransformError> {
        self.output.push(b'"');
        self.output.extend_from_slice(value);
        self.output.push(b'"');
        self.needs_comma = true;
        Ok(())
    }

    #[inline(always)]
    pub fn write_raw(&mut self, value: &[u8]) -> Result<(), TransformError> {
        self.output.extend_from_slice(value);
        self.needs_comma = true;
        Ok(())
    }

    #[inline(always)]
    pub fn write_null(&mut self) -> Result<(), TransformError> {
        self.output.extend_from_slice(b"null");
        self.needs_comma = true;
        Ok(())
    }

    #[inline(always)]
    pub fn write_object_start(&mut self) -> Result<(), TransformError> {
        self.output.push(b'{');
        self.needs_comma = false;
        Ok(())
    }

    #[inline(always)]
    pub fn write_object_end(&mut self) -> Result<(), TransformError> {
        self.output.push(b'}');
        self.needs_comma = true;
        Ok(())
    }

    #[inline(always)]
    pub fn write_array_start(&mut self) -> Result<(), TransformError> {
        self.output.push(b'[');
        self.needs_comma = false;
        Ok(())
    }

    #[inline(always)]
    pub fn write_array_end(&mut self) -> Result<(), TransformError> {
        self.output.push(b']');
        self.needs_comma = true;
        Ok(())
    }

    /// Write comma separator (for array elements)
    #[inline(always)]
    pub fn write_comma(&mut self) -> Result<(), TransformError> {
        self.output.push(b',');
        self.needs_comma = false;
        Ok(())
    }

    /// Write escaped bytes
    ///
    /// Properly escapes JSON special characters
    #[inline]
    fn write_escaped(&mut self, bytes: &[u8]) -> Result<(), TransformError> {
        escape_json_string_scalar(bytes, self.output.as_mut_vec());
        Ok(())
    }
}

/// JSON string escaping with proper character handling
#[inline]
fn escape_json_string_scalar(input: &[u8], output: &mut Vec<u8>) {
    for &byte in input {
        match byte {
            b'"' => output.extend_from_slice(b"\\\""),
            b'\\' => output.extend_from_slice(b"\\\\"),
            b'\n' => output.extend_from_slice(b"\\n"),
            b'\r' => output.extend_from_slice(b"\\r"),
            b'\t' => output.extend_from_slice(b"\\t"),
            0..=0x1F => {
                output.extend_from_slice(b"\\u00");
                let hex = byte / 16;
                output.push(b"0123456789abcdef"[hex as usize]);
                let hex = byte % 16;
                output.push(b"0123456789abcdef"[hex as usize]);
            },
            _ => output.push(byte),
        }
    }
}

/// Transform errors
#[derive(Debug)]
pub enum TransformError {
    UnexpectedEof,
    UnexpectedByte(u8),
    ExpectedByte(u8, u8),
    UnterminatedString,
    InvalidBool,
    InvalidNull,
    InvalidNumber,
    MaxDepthExceeded(usize),
}

impl std::fmt::Display for TransformError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            TransformError::UnexpectedEof => write!(f, "Unexpected end of input"),
            TransformError::UnexpectedByte(b) => write!(f, "Unexpected byte: {}", b),
            TransformError::ExpectedByte(expected, got) => {
                write!(f, "Expected byte {}, got {}", expected, got)
            },
            TransformError::UnterminatedString => write!(f, "Unterminated string"),
            TransformError::InvalidBool => write!(f, "Invalid boolean value"),
            TransformError::InvalidNull => write!(f, "Invalid null value"),
            TransformError::InvalidNumber => write!(f, "Invalid number"),
            TransformError::MaxDepthExceeded(max) => {
                write!(f, "JSON nesting depth exceeded maximum of {}", max)
            },
        }
    }
}

impl std::error::Error for TransformError {}

impl From<TransformError> for PyErr {
    fn from(err: TransformError) -> PyErr {
        pyo3::exceptions::PyValueError::new_err(err.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn transform(input: &str, typename: Option<&str>) -> String {
        let config = TransformConfig {
            add_typename: true,
            camel_case: true,
            project_fields: false,
            add_graphql_wrapper: false,
            max_depth: MAX_JSON_DEPTH,
        };
        let mut transformer = ZeroCopyTransformer::new(config, typename, None);
        let mut output = ByteBuf::with_estimated_capacity(input.len(), &config);
        transformer.transform_bytes(input.as_bytes(), &mut output).unwrap();
        String::from_utf8(output.into_vec()).unwrap()
    }

    #[test]
    fn typename_is_the_rows_not_the_nested_objects() {
        // A nested object is of its own type: it was given the row's name
        let out = transform(
            r#"{"id":"a1","device":{"id":"d1","is_active":true},"devices":[{"id":"d1"}]}"#,
            Some("Assignment"),
        );
        assert_eq!(
            out,
            r#"{"__typename":"Assignment","id":"a1","device":{"id":"d1","isActive":true},"devices":[{"id":"d1"}]}"#
        );
    }

    #[test]
    fn each_object_of_an_array_row_is_a_row() {
        let out = transform(r#"[{"id":1,"owner":{"id":2}},{"id":3}]"#, Some("Post"));
        assert_eq!(
            out,
            r#"[{"__typename":"Post","id":1,"owner":{"id":2}},{"__typename":"Post","id":3}]"#
        );
    }

    #[test]
    fn a_nested_typename_in_the_json_is_kept() {
        let out = transform(
            r#"{"__typename":"Stale","device":{"__typename":"Device","id":"d1"}}"#,
            Some("Assignment"),
        );
        assert_eq!(
            out,
            r#"{"__typename":"Assignment","device":{"__typename":"Device","id":"d1"}}"#
        );
    }

    #[test]
    fn without_a_typename_nothing_is_injected() {
        let out = transform(r#"{"id":1,"__typename":"Row","child":{"a_b":1}}"#, None);
        assert_eq!(out, r#"{"id":1,"__typename":"Row","child":{"aB":1}}"#);
    }

    #[test]
    fn escaped_strings_are_copied_as_they_are() {
        // Escaped again, "a\"b" became "a\\\"b": the client read a\"b
        let input = r#"{"t":"a\"b\\c\né","end":"x\\","k\"ey":1}"#;
        let out = transform(input, None);
        assert_eq!(out, input);
        let parsed: serde_json::Value = serde_json::from_str(&out).unwrap();
        assert_eq!(parsed["t"], "a\"b\\c\n\u{e9}");
        assert_eq!(parsed["end"], "x\\");
    }

    fn project(input: &str, typename: Option<&str>, projection: &Projection) -> String {
        let config = TransformConfig {
            add_typename: typename.is_some(),
            camel_case: true,
            project_fields: true,
            add_graphql_wrapper: false,
            max_depth: MAX_JSON_DEPTH,
        };
        let mut transformer = ZeroCopyTransformer::new(config, typename, Some(projection));
        let mut output = ByteBuf::with_estimated_capacity(input.len(), &config);
        transformer.transform_bytes(input.as_bytes(), &mut output).unwrap();
        String::from_utf8(output.into_vec()).unwrap()
    }

    fn selections(list: &[(&str, &str, bool)]) -> Projection {
        let values: Vec<serde_json::Value> = list
            .iter()
            .map(|(path, response_path, is_object)| {
                serde_json::json!({"materialized_path": path, "response_path": response_path,
                                   "is_nested_object": is_object})
            })
            .collect();
        Projection::from_selections(&values)
    }

    #[test]
    fn a_key_hashing_like_a_selected_one_is_not_written() {
        // "author" and "secret_note17" fell on one bit of the old 128-bit hash map
        let projection = selections(&[
            ("author", "author", true),
            ("author.id", "author.id", false),
        ]);
        let out = project(
            r#"{"id":1,"author":{"id":2,"pw":"x"},"secret_note17":"LEAK","secret_note":"s"}"#,
            Some("Post"),
            &projection,
        );
        assert_eq!(out, r#"{"__typename":"Post","author":{"id":2}}"#);
    }

    #[test]
    fn nested_selections_are_kept_under_their_keys() {
        let projection = selections(&[
            ("author_info", "author_info", true),
            ("author_info.first_name", "author_info.first_name", false),
            ("created_at", "created_at", false),
        ]);
        let out = project(
            r#"{"created_at":"c","author_info":{"first_name":"f","last_name":"l"}}"#,
            None,
            &projection,
        );
        assert_eq!(out, r#"{"created_at":"c","author_info":{"first_name":"f"}}"#);
    }

    #[test]
    fn a_list_of_objects_is_projected_element_by_element() {
        let projection = selections(&[("tags", "labels", true), ("tags.name", "labels.n", false)]);
        let out = project(r#"{"tags":[{"name":"a","x":1},null,{"name":"b"}]}"#, None, &projection);
        assert_eq!(out, r#"{"labels":[{"n":"a"},null,{"n":"b"}]}"#);
    }

    #[test]
    fn two_aliases_of_one_field_read_it_twice() {
        let projection = selections(&[
            ("device", "d", true),
            ("device.id", "d.id", false),
            ("device", "e", true),
            ("device.device_name", "e.name", false),
        ]);
        let out =
            project(r#"{"device":{"id":"d1","device_name":"n"},"id":"a"}"#, None, &projection);
        assert_eq!(out, r#"{"d":{"id":"d1"},"e":{"name":"n"}}"#);
    }

    #[test]
    fn a_leaf_is_copied_as_it_is() {
        // A JSON scalar's keys are data, not field names
        let projection = selections(&[("meta", "meta", false)]);
        let out = project(r#"{"meta":{"some_key":[1, {"a_b":2}]}}"#, None, &projection);
        assert_eq!(out, r#"{"meta":{"some_key":[1, {"a_b":2}]}}"#);
    }

    #[test]
    fn a_selected_key_is_found_camel_cased_too() {
        let projection = selections(&[("first_name", "firstName", false)]);
        assert_eq!(project(r#"{"firstName":"a"}"#, None, &projection), r#"{"firstName":"a"}"#);
        // Both spellings in the JSON: the field is written once
        assert_eq!(
            project(r#"{"first_name":"a","firstName":"b"}"#, None, &projection),
            r#"{"firstName":"a"}"#
        );
    }
}

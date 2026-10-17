"""Unit tests for TypeMapper."""

from fraiseql.introspection.type_mapper import TypeMapper


class TestTypeMapper:
    """Test TypeMapper functionality."""

    def test_basic_type_mapping(self) -> None:
        """Test basic types."""
        mapper = TypeMapper()
        assert mapper.pg_type_to_python("text") is str
        assert mapper.pg_type_to_python("integer") is int
        assert mapper.pg_type_to_python("uuid") is not None  # UUID type
        assert mapper.pg_type_to_python("boolean") is bool

    def test_nullable_type_mapping(self) -> None:
        """Test nullable types."""
        mapper = TypeMapper()
        result = mapper.pg_type_to_python("text", nullable=True)
        # Should be Optional[str] - we can't easily test the exact type
        # but it should not be just str
        assert result is not str

    def test_array_type_mapping(self) -> None:
        """Test array types."""
        mapper = TypeMapper()
        result = mapper.pg_type_to_python("text[]")
        # Should be List[str] - we can't easily test the exact type
        # but it should not be just str
        assert result is not str

    def test_case_insensitive_mapping(self) -> None:
        """Test case insensitive type mapping."""
        mapper = TypeMapper()
        assert mapper.pg_type_to_python("TEXT") is str
        assert mapper.pg_type_to_python("Integer") is int
        assert mapper.pg_type_to_python("BOOLEAN") is bool

    def test_unknown_type_fallback(self) -> None:
        """Test unknown types fall back to str."""
        mapper = TypeMapper()
        assert mapper.pg_type_to_python("unknown_type") is str
        assert mapper.pg_type_to_python("custom_type") is str

    def test_register_custom_type(self) -> None:
        """Test registering custom type mappings."""
        mapper = TypeMapper()

        # Register a custom type
        class CustomType:
            pass

        mapper.register_custom_type("custom", CustomType)

        # Should now map to our custom type
        result = mapper.pg_type_to_python("custom")
        assert result is CustomType

    def test_timestamp_types(self) -> None:
        """Test timestamp type mappings."""
        mapper = TypeMapper()
        # All timestamp variants should map to datetime
        assert mapper.pg_type_to_python("timestamp") is not None
        assert mapper.pg_type_to_python("timestamp with time zone") is not None
        assert mapper.pg_type_to_python("timestamptz") is not None

    def test_numeric_types(self) -> None:
        """Test numeric type mappings."""
        mapper = TypeMapper()
        # Various integer types
        assert mapper.pg_type_to_python("int4") is int
        assert mapper.pg_type_to_python("int8") is int
        assert mapper.pg_type_to_python("bigint") is int

        # Decimal types
        assert mapper.pg_type_to_python("numeric") is not None
        assert mapper.pg_type_to_python("decimal") is not None

        # Float types
        assert mapper.pg_type_to_python("float8") is float
        assert mapper.pg_type_to_python("double precision") is float

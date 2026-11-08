"""Vector scalar types for PostgreSQL pgvector.

Supports two vector types, which read and write as ``list[float]``:
- Vector: Standard 32-bit float vectors
- HalfVector: 16-bit half-precision vectors (50% memory savings)

There is no sparse or quantized vector type. A ``sparsevec`` column reads back
as text (``{1:0.5,3:0.2}/5``), and a sparse operand can't be filtered or sorted
on: its literal needs the column's dimension. pgvector has no quantized type.

Minimal validation following FraiseQL philosophy:
- Verify value is list of numbers
- Let PostgreSQL handle dimension validation
- No conversion or transformation
"""

from typing import Any

from graphql import GraphQLError, GraphQLScalarType

from fraiseql.types.definitions import ScalarMarker


def serialize_vector(value: Any) -> list[float]:
    """Serialize vector to GraphQL output (no transformation).

    Args:
        value: The vector value to serialize

    Returns:
        The vector as a list of floats

    Raises:
        GraphQLError: If the value is not a valid vector
    """
    if not isinstance(value, list):
        msg = f"Vector must be a list, got {type(value).__name__}"
        raise GraphQLError(msg)

    if not all(isinstance(x, (int, float)) for x in value):
        msg = "All vector values must be numbers"
        raise GraphQLError(msg)

    # Return as floats for consistency, but don't modify original
    return [float(x) for x in value]


def parse_vector_value(value: Any) -> list[float]:
    """Parse GraphQL input to vector (basic validation only).

    Args:
        value: Input value from GraphQL

    Returns:
        Validated vector as list of floats

    Raises:
        GraphQLError: If value is not a list or contains non-numeric elements
    """
    if not isinstance(value, list):
        msg = f"Vector must be a list of floats, got {type(value).__name__}"
        raise GraphQLError(msg)

    if not all(isinstance(x, (int, float)) for x in value):
        msg = "All vector values must be numbers"
        raise GraphQLError(msg)

    # NO dimension validation - let PostgreSQL handle it
    # Coerce integers to floats for consistency
    return [float(x) for x in value]


# GraphQL scalar definitions
VectorScalar = GraphQLScalarType(
    name="Vector",
    description=(
        "PostgreSQL vector type for pgvector extension. "
        "Represents vector embeddings as lists of floats. "
        "Distance operators available: cosine_distance, l2_distance, inner_product."
    ),
    serialize=serialize_vector,
    parse_value=parse_vector_value,
    parse_literal=None,  # Vectors are typically passed as variables, not literals
)

HalfVectorScalar = GraphQLScalarType(
    name="HalfVector",
    description=(
        "PostgreSQL halfvec type for pgvector extension. "
        "Half-precision 16-bit float vectors with 50% memory savings. "
        "Same distance operators as Vector type but reduced precision."
    ),
    serialize=serialize_vector,  # Same serialization as regular vectors
    parse_value=parse_vector_value,  # Same parsing as regular vectors
    parse_literal=None,  # Vectors are typically passed as variables, not literals
)


# Python markers for use in dataclasses
class VectorField(list[float], ScalarMarker):
    """Python marker for a pgvector ``vector`` column, which behaves as ``list[float]``.

    It reads and writes as ``[Float]`` and gets the vector ``where`` and
    ``orderBy`` operators, whatever the field is named:

    ```python
    @type(sql_source="documents")
    class Document:
        id: UUID
        embedding: VectorField
    ```
    """

    __slots__ = ()

    def __repr__(self) -> str:
        """String representation used in type annotations and debug output."""
        return "Vector"


class HalfVectorField(list[float], ScalarMarker):
    """Python marker for a pgvector ``halfvec`` column, which behaves as ``list[float]``.

    It reads and writes as ``[Float]`` and gets the vector ``where`` and
    ``orderBy`` operators, whatever the field is named:

    ```python
    @type(sql_source="documents")
    class Document:
        id: UUID
        embedding: HalfVectorField  # halfvec: half the storage of vector
    ```
    """

    __slots__ = ()

    def __repr__(self) -> str:
        """String representation used in type annotations and debug output."""
        return "HalfVector"


def is_float_vector_type(typ: Any) -> bool:
    """Whether typ is ``VectorField`` or ``HalfVectorField``, which mean ``list[float]``."""
    return isinstance(typ, type) and issubclass(typ, (VectorField, HalfVectorField))

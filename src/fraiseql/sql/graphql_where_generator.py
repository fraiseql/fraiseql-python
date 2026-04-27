"""GraphQL-compatible where input type generator.

This module provides utilities to dynamically generate GraphQL input types
that support operator-based filtering. These types can be used directly in
GraphQL resolvers and are automatically converted to SQL where types.

Custom Scalar WHERE Filter Support
===================================

This module extends FraiseQL's WHERE clause generation to support custom
GraphQL scalar types. Previously, all custom scalars defaulted to StringFilter,
causing type mismatches in GraphQL queries.

Key Features:
- Automatic detection of GraphQLScalarType instances
- Generation of type-specific filters (CIDRFilter, EmailFilter, etc.)
- Standard operators: eq, ne, in, notIn, contains, startsWith, endsWith
- Caching to prevent duplicate filter generation
- Full GraphQL schema integration

Example:
    @fraise_type
    class NetworkDevice:
        ip_address: CIDRScalar

    # Generates:
    input NetworkDeviceWhereInput {
        ipAddress: CIDRFilter
    }

    input CIDRFilter {
        eq: CIDR
        ne: CIDR
        in: [CIDR!]
        notIn: [CIDR!]
        contains: CIDR
        startsWith: CIDR
        endsWith: CIDR
    }
"""

import logging
from dataclasses import make_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional, TypeVar, Union, get_args, get_origin, get_type_hints
from uuid import UUID

# Import GraphQL types for custom scalar detection
from graphql import GraphQLScalarType

# Type alias for better readability
FilterFieldSpec = tuple[type, Any, str | None]  # (field_type, default_value, graphql_name)

from fraiseql import fraise_input
from fraiseql.fields import fraise_field
from fraiseql.sql.where_generator import safe_create_where_type
from fraiseql.types.scalars.vector import HalfVectorField, QuantizedVectorField, SparseVectorField

logger = logging.getLogger(__name__)

# Type variable for generic filter types
T = TypeVar("T")

# Cache for generated where input types to handle circular references
_where_input_cache: dict[type, type] = {}
# Stack to track types being generated to detect circular references
_generation_stack: set[type] = set()
# Cache for custom scalar filter types
_custom_scalar_filter_cache: dict[GraphQLScalarType, type] = {}


# Base operator filter types for GraphQL inputs
@fraise_input
class StringFilter:
    """String field filter operations."""

    eq: str | None = None
    neq: str | None = None
    contains: str | None = None
    icontains: str | None = None
    startswith: str | None = None
    istartswith: str | None = None
    endswith: str | None = None
    iendswith: str | None = None
    like: str | None = None
    ilike: str | None = None
    matches: str | None = None
    imatches: str | None = None
    not_matches: str | None = None
    in_: list[str] | None = fraise_field(default=None, graphql_name="in")
    nin: list[str] | None = None
    notin: list[str] | None = None  # Alias for nin
    isnull: bool | None = None


@fraise_input
class ArrayFilter:
    """Array field filter operations.

    Provides comprehensive array filtering with PostgreSQL array operators:
    - Equality: eq, neq
    - Containment: contains, contained_by, strictly_contains
    - Overlap: overlaps
    - Length: len_eq, len_neq, len_gt, len_gte, len_lt, len_lte
    - Element matching: any_eq, all_eq, in_array

    Prefixed versions (array_*) are aliases for consistency with other codebases.
    """

    # Basic equality
    eq: list | None = None
    neq: list | None = None
    isnull: bool | None = None

    # Containment operators
    contains: list | None = None  # Array contains all elements
    contained_by: list | None = None  # Array is contained by
    strictly_contains: list | None = None  # Array strictly contains (proper superset)
    overlaps: list | None = None  # Arrays have common elements

    # Length operators
    len_eq: int | None = None
    len_neq: int | None = None
    len_gt: int | None = None
    len_gte: int | None = None
    len_lt: int | None = None
    len_lte: int | None = None

    # Element matching
    any_eq: str | None = None  # Any element equals value
    all_eq: str | None = None  # All elements equal value
    in_array: str | None = None  # Value is in array (reverse of contains)

    # Prefixed aliases for compatibility
    array_eq: list | None = None
    array_neq: list | None = None
    array_contains: list | None = None
    array_contained_by: list | None = None
    array_overlaps: list | None = None
    array_length_eq: int | None = None
    array_length_gt: int | None = None
    array_length_gte: int | None = None
    array_length_lt: int | None = None
    array_any_eq: str | None = None
    array_all_eq: str | None = None


@fraise_input
class IntFilter:
    """Integer field filter operations."""

    eq: int | None = None
    neq: int | None = None
    gt: int | None = None
    gte: int | None = None
    lt: int | None = None
    lte: int | None = None
    in_: list[int] | None = fraise_field(default=None, graphql_name="in")
    nin: list[int] | None = None
    isnull: bool | None = None


@fraise_input
class FloatFilter:
    """Float field filter operations."""

    eq: float | None = None
    neq: float | None = None
    gt: float | None = None
    gte: float | None = None
    lt: float | None = None
    lte: float | None = None
    in_: list[float] | None = fraise_field(default=None, graphql_name="in")
    nin: list[float] | None = None
    isnull: bool | None = None


@fraise_input
class DecimalFilter:
    """Decimal field filter operations."""

    eq: Decimal | None = None
    neq: Decimal | None = None
    gt: Decimal | None = None
    gte: Decimal | None = None
    lt: Decimal | None = None
    lte: Decimal | None = None
    in_: list[Decimal] | None = fraise_field(default=None, graphql_name="in")
    nin: list[Decimal] | None = None
    isnull: bool | None = None


@fraise_input
class BooleanFilter:
    """Boolean field filter operations."""

    eq: bool | None = None
    neq: bool | None = None
    isnull: bool | None = None


@fraise_input
class UUIDFilter:
    """UUID field filter operations."""

    eq: UUID | None = None
    neq: UUID | None = None
    in_: list[UUID] | None = fraise_field(default=None, graphql_name="in")
    nin: list[UUID] | None = None
    isnull: bool | None = None
    descendant_of_id: str | None = None  # IN (SELECT id FROM tb_entity WHERE path <@ subquery)
    ancestor_of_id: str | None = None  # IN (SELECT id FROM tb_entity WHERE path @> subquery)


# Import ID type for IDFilter
from fraiseql.types import ID


@fraise_input
class IDFilter:
    """GraphQL ID field filter operations.

    Used for filtering on ID fields in where clauses. The ID type
    accepts any string value (UUIDs, integers, slugs, etc.) as per
    GraphQL specification.
    """

    eq: ID | None = None
    neq: ID | None = None
    in_: list[ID] | None = fraise_field(default=None, graphql_name="in")
    nin: list[ID] | None = None
    isnull: bool | None = None


@fraise_input
class DateFilter:
    """Date field filter operations."""

    eq: date | None = None
    neq: date | None = None
    gt: date | None = None
    gte: date | None = None
    lt: date | None = None
    lte: date | None = None
    in_: list[date] | None = fraise_field(default=None, graphql_name="in")
    nin: list[date] | None = None
    isnull: bool | None = None


@fraise_input
class DateTimeFilter:
    """DateTime field filter operations."""

    eq: datetime | None = None
    neq: datetime | None = None
    gt: datetime | None = None
    gte: datetime | None = None
    lt: datetime | None = None
    lte: datetime | None = None
    in_: list[datetime] | None = fraise_field(default=None, graphql_name="in")
    nin: list[datetime] | None = None
    isnull: bool | None = None


# IPRange input type for network range filtering
@fraise_input
class IPRange:
    """IP address range input for network filtering operations."""

    from_: str = fraise_field(graphql_name="from")
    to: str


# Restricted filter types for exotic scalar types that have normalization issues
@fraise_input
class NetworkAddressFilter:
    """Enhanced filter for IP addresses and CIDR with network-specific operations.

    Provides network-aware filtering operations like subnet matching, IP range queries,
    and private/public network detection. Basic string operations are excluded due to
    PostgreSQL inet/cidr type normalization issues.
    """

    # Basic equality operations
    eq: str | None = None
    neq: str | None = None
    in_: list[str] | None = fraise_field(default=None, graphql_name="in")
    nin: list[str] | None = None
    isnull: bool | None = None

    # Network-specific operations (v0.3.8+)
    inSubnet: str | None = None  # IP is in CIDR subnet  # noqa: N815
    inRange: IPRange | None = None  # IP is in range  # noqa: N815
    isPrivate: bool | None = None  # RFC 1918 private address  # noqa: N815
    isPublic: bool | None = None  # Non-private address  # noqa: N815
    isIPv4: bool | None = None  # IPv4 address  # noqa: N815
    isIPv6: bool | None = None  # IPv6 address  # noqa: N815

    # Lowercase aliases for network operations
    insubnet: str | None = None  # Alias for inSubnet
    inrange: IPRange | None = None  # Alias for inRange
    isprivate: bool | None = None  # Alias for isPrivate
    ispublic: bool | None = None  # Alias for isPublic
    isipv4: bool | None = None  # Alias for isIPv4
    isipv6: bool | None = None  # Alias for isIPv6

    # CIDR positioning operators
    strictleft: str | None = None  # << operator - strictly left of
    strictright: str | None = None  # >> operator - strictly right of

    # Advanced network classification (v0.6.1+)
    isLoopback: bool | None = None  # Loopback address (127.0.0.1, ::1)  # noqa: N815
    isMulticast: bool | None = None  # Multicast address (224.0.0.0/4, ff00::/8)  # noqa: N815
    isBroadcast: bool | None = None  # Broadcast address (255.255.255.255)  # noqa: N815
    isLinkLocal: bool | None = None  # Link-local address (169.254.0.0/16, fe80::/10)  # noqa: N815
    isDocumentation: bool | None = None  # RFC 3849/5737 documentation ranges  # noqa: N815
    isReserved: bool | None = None  # Reserved/unspecified address (0.0.0.0, ::)  # noqa: N815
    isCarrierGrade: bool | None = None  # Carrier-Grade NAT (100.64.0.0/10)  # noqa: N815
    isSiteLocal: bool | None = None  # Site-local IPv6 (fec0::/10 - deprecated)  # noqa: N815
    isUniqueLocal: bool | None = None  # Unique local IPv6 (fc00::/7)  # noqa: N815
    isGlobalUnicast: bool | None = None  # Global unicast address  # noqa: N815

    # Intentionally excludes: contains, startswith, endswith


@fraise_input
class MacAddressFilter:
    """Restricted filter for MAC addresses that only exposes working operators.

    Excludes string pattern matching due to PostgreSQL macaddr type normalization
    where values are automatically formatted to canonical form.
    """

    eq: str | None = None
    neq: str | None = None
    in_: list[str] | None = fraise_field(default=None, graphql_name="in")
    nin: list[str] | None = None
    isnull: bool | None = None
    # Intentionally excludes: contains, startswith, endswith


@fraise_input
class LTreeFilter:
    """Filter for LTree hierarchical paths with comprehensive operator support.

    Provides complete set of PostgreSQL ltree operators for path filtering, analysis,
    and manipulation. Organized into six categories:

    **Path Comparison Operators** (Lexicographic Ordering):
    - eq, neq: Path equality/inequality
    - lt, lte, gt, gte: Lexicographic path comparison

    **Hierarchy Operators** (Ancestor/Descendant Relationships):
    - ancestor_of (@>): Is ancestor of path
    - descendant_of (<@): Is descendant of path
    - isdescendant: Alias for descendant_of

    **Pattern Matching Operators**:
    - matches_lquery (~): Matches lquery pattern with wildcards
    - matches_ltxtquery (?): Matches ltxtquery text pattern (AND/OR/NOT logic)
    - matches_any_lquery: Matches any of multiple lquery patterns

    **Path Depth Operators** (using nlevel() function):
    - nlevel: Get path depth (returns integer)
    - nlevel_eq, nlevel_neq: Exact depth matching
    - nlevel_gt, nlevel_gte: Depth greater than
    - nlevel_lt, nlevel_lte: Depth less than
    - depth_*: Aliases for nlevel_* (same semantics)

    **Path Analysis Operators** (Extract and Find):
    - index(label): Find position of label in path
    - index_eq(label, pos): Label at exact position
    - index_gte(label, pos): Label at or after position
    - subpath(offset, len): Extract subpath range

    **Path Manipulation Operators**:
    - concat(path): Concatenate with another path
    - lca(paths): Lowest common ancestor of multiple paths

    **Array Operations**:
    - in_array(paths): Path is in array of allowed paths
    - array_contains(path): Array field contains target path
    - matches_any_lquery(patterns): Path matches any of multiple lquery patterns
    """

    # Basic comparison operators
    eq: str | None = None
    neq: str | None = None
    lt: str | None = None  # Path less than (lexicographic)
    lte: str | None = None  # Path less than or equal (lexicographic)
    gt: str | None = None  # Path greater than (lexicographic)
    gte: str | None = None  # Path greater than or equal (lexicographic)
    in_: list[str] | None = fraise_field(default=None, graphql_name="in")
    nin: list[str] | None = None
    isnull: bool | None = None

    # LTree-specific hierarchical operators
    ancestor_of: str | None = None  # @> - Is ancestor of path
    descendant_of: str | None = None  # <@ - Is descendant of path
    isdescendant: str | None = None  # Alias for descendant_of
    matches_lquery: str | None = None  # ~ - Matches lquery pattern
    matches_ltxtquery: str | None = None  # ? - Matches ltxtquery text pattern
    matches_any_lquery: list[str] | None = None  # ? ANY(lquery[]) - Matches any lquery

    # Level/depth operators (nlevel() function)
    nlevel: int | None = None  # Exact level count: nlevel(path) = value
    nlevel_eq: int | None = None  # nlevel(path) = value
    nlevel_gt: int | None = None  # nlevel(path) > value
    nlevel_gte: int | None = None  # nlevel(path) >= value
    nlevel_lt: int | None = None  # nlevel(path) < value
    nlevel_lte: int | None = None  # nlevel(path) <= value
    nlevel_neq: int | None = None  # nlevel(path) != value

    # Depth aliases (same semantics as nlevel)
    depth_eq: int | None = None  # Alias for nlevel_eq
    depth_gt: int | None = None  # Alias for nlevel_gt
    depth_gte: int | None = None  # Alias for nlevel_gte
    depth_lt: int | None = None  # Alias for nlevel_lt
    depth_lte: int | None = None  # Alias for nlevel_lte
    depth_neq: int | None = None  # Alias for nlevel_neq

    # Path manipulation operators
    subpath: str | None = None  # subpath(path, offset, len) comparison
    index: int | None = None  # index(path, item) - position of item
    index_eq: int | None = None  # index(path, item) = value
    index_gte: int | None = None  # index(path, item) >= value
    lca: list[str] | None = None  # Lowest Common Ancestor of paths
    concat: str | None = None  # path || value - concatenation

    # Array operations
    in_array: list[str] | None = None  # <@ - Path is in array of paths
    array_contains: str | None = None  # @> - Array contains path


@fraise_input
class DateRangeFilter:
    """Filter for PostgreSQL date range types with full operator support.

    Provides both basic comparison operators and PostgreSQL range-specific
    operators for containment, overlap, adjacency, and positioning queries.
    """

    # Basic comparison operators
    eq: str | None = None
    neq: str | None = None
    in_: list[str] | None = fraise_field(default=None, graphql_name="in")
    nin: list[str] | None = None
    isnull: bool | None = None

    # Range-specific operators
    contains_date: str | None = None  # @> - Range contains date/range
    overlaps: str | None = None  # && - Ranges overlap
    adjacent: str | None = None  # -|- - Ranges are adjacent

    # Range positioning operators
    strictly_left: str | None = None  # << - Strictly left of
    strictly_right: str | None = None  # >> - Strictly right of
    not_left: str | None = None  # &> - Does not extend to the left
    not_right: str | None = None  # &< - Does not extend to the right

    # Intentionally excludes string pattern matching (use range operators instead)


@fraise_input
class FullTextFilter:
    """Filter for PostgreSQL full-text search (tsvector) with comprehensive search operators.

    Provides PostgreSQL's full-text search capabilities including basic search,
    advanced query parsing, and relevance ranking.
    """

    # Basic search operators
    matches: str | None = None  # @@ with to_tsquery()
    plain_query: str | None = None  # @@ with plainto_tsquery()

    # Advanced query types
    phrase_query: str | None = None  # @@ with phraseto_tsquery()
    websearch_query: str | None = None  # @@ with websearch_to_tsquery()

    # Relevance ranking operators (format: "query:threshold")
    rank_gt: str | None = None  # ts_rank() >
    rank_gte: str | None = None  # ts_rank() >=
    rank_lt: str | None = None  # ts_rank() <
    rank_lte: str | None = None  # ts_rank() <=

    # Cover density ranking operators (format: "query:threshold")
    rank_cd_gt: str | None = None  # ts_rank_cd() >
    rank_cd_gte: str | None = None  # ts_rank_cd() >=
    rank_cd_lt: str | None = None  # ts_rank_cd() <
    rank_cd_lte: str | None = None  # ts_rank_cd() <=

    # Basic null check
    isnull: bool | None = None


@fraise_input
class JSONBFilter:
    """Filter for PostgreSQL JSONB with comprehensive operator support.

    Provides PostgreSQL's JSONB capabilities including key existence,
    containment, JSONPath queries, and deep path access.
    """

    # Basic comparison operators
    eq: Any | None = None  # Exact equality (accepts dict or list)
    neq: Any | None = None  # Not equal (accepts dict or list)
    isnull: bool | None = None  # Null check

    # Key existence operators
    has_key: str | None = None  # ? operator
    has_any_keys: list[str] | None = None  # ?| operator
    has_all_keys: list[str] | None = None  # ?& operator

    # Containment operators
    contains: Any | None = None  # @> operator (accepts dict or list)
    contained_by: Any | None = None  # <@ operator (accepts dict or list)

    # JSONPath operators
    path_exists: str | None = None  # @? operator
    path_match: str | None = None  # @@ operator


# Input type for sparse vectors
@fraise_input
class SparseVectorInput:
    """Sparse vector input with indices and values."""

    indices: list[int]
    values: list[float]


# Input type for vector distance operations (supports both dense and sparse)
@fraise_input
class VectorDistanceInput:
    """Input for vector distance operations.

    Supports both dense vectors (as list of floats) and sparse vectors.
    Exactly one of 'dense' or 'sparse' must be provided.

    Examples:
        # Dense vector:
        { dense: [0.1, 0.2, 0.3, 0.4] }

        # Sparse vector:
        { sparse: { indices: [1, 3, 5], values: [0.1, 0.2, 0.3] } }
    """

    dense: list[float] | None = None
    sparse: SparseVectorInput | None = None


@fraise_input
class VectorFilter:
    """PostgreSQL pgvector field filter operations.

    Exposes native pgvector distance operators transparently:

    Float Vector Operators (vector/halfvec):
    - cosine_distance: Cosine distance (0.0 = identical, 2.0 = opposite)
    - l2_distance: L2/Euclidean distance (0.0 = identical, ∞ = very different)
    - l1_distance: L1/Manhattan distance (sum of absolute differences)
    - inner_product: Negative inner product (more negative = more similar)

    Sparse Vector Operators (sparsevec):
    - cosine_distance: Sparse cosine distance (accepts sparse vector input)
    - l2_distance: Sparse L2 distance (accepts sparse vector input)
    - inner_product: Sparse inner product (accepts sparse vector input)

    Binary Vector Operators (bit):
    - hamming_distance: Hamming distance for bit vectors (count differing bits)
    - jaccard_distance: Jaccard distance for set similarity (1 - intersection/union)

    Distance values are returned raw from PostgreSQL (no conversion).
    Requires pgvector extension: CREATE EXTENSION vector;

    Example:
        # Dense vector distance:
        documents(
            where: { embedding: { cosine_distance: { dense: [0.1, 0.2, 0.3] } } }
            limit: 10
        )
        # Sparse vector distance:
        documents(
            where: {
                sparse_embedding: {
                    cosine_distance: { sparse: { indices: [1,3,5], values: [0.1,0.2,0.3] } }
                }
            }
        )
        # Binary vector distance:
        documents(
            where: { binary_embedding: { hamming_distance: "101010" } }
        )
    """

    # Float vector operators (accept VectorDistanceInput for both dense and sparse)
    cosine_distance: VectorDistanceInput | None = None
    l2_distance: VectorDistanceInput | None = None
    l1_distance: VectorDistanceInput | None = None
    inner_product: VectorDistanceInput | None = None

    # Distance threshold filter (maximum distance to include)
    distance_within: float | None = None

    # Binary vector operators (bit string like "101010")
    hamming_distance: str | None = None
    jaccard_distance: str | None = None

    isnull: bool | None = None


def _create_custom_scalar_filter(scalar_type: GraphQLScalarType) -> type:
    """Create a filter type for a custom GraphQL scalar.

    Generates a filter with standard operators (eq, ne, in, notIn, contains,
    startsWith, endsWith) that accept the scalar type instead of String.

    This enables type-safe WHERE filtering for custom scalars like CIDR,
    Email, Color, etc.

    Args:
        scalar_type: The GraphQL scalar type to create a filter for

    Returns:
        A new dataclass decorated with @fraise_input for GraphQL input types

    Example:
        _create_custom_scalar_filter(CIDRScalar) -> CIDRFilter class
    """
    # Check cache first to avoid duplicate filter generation
    if scalar_type in _custom_scalar_filter_cache:
        return _custom_scalar_filter_cache[scalar_type]

    # Generate filter name (e.g., CIDRScalar -> CIDRFilter)
    scalar_name = scalar_type.name
    if scalar_name.endswith("Scalar"):
        filter_name = scalar_name.replace("Scalar", "Filter")
    else:
        filter_name = f"{scalar_name}Filter"

    # Create the filter class with standard operators
    # We use manual class creation since make_dataclass can't handle fraise_field
    class CustomScalarFilter:
        """Filter operations for custom scalar types."""

        # Equality and comparison operators
        eq: Optional[scalar_type] = None
        ne: Optional[scalar_type] = None

        # List membership operators (with GraphQL name mapping)
        in_: Optional[list[scalar_type]] = fraise_field(default=None, graphql_name="in")
        not_in: Optional[list[scalar_type]] = fraise_field(default=None, graphql_name="notIn")

        # String pattern matching operators (may be useful for custom scalars)
        contains: Optional[scalar_type] = None
        starts_with: Optional[scalar_type] = fraise_field(default=None, graphql_name="startsWith")
        ends_with: Optional[scalar_type] = fraise_field(default=None, graphql_name="endsWith")

    # Set the class name dynamically
    CustomScalarFilter.__name__ = filter_name
    CustomScalarFilter.__qualname__ = filter_name

    # Mark as FraiseQL input type for GraphQL schema generation
    filter_class = fraise_input(CustomScalarFilter)

    # Cache it to prevent regeneration for the same scalar type
    _custom_scalar_filter_cache[scalar_type] = filter_class

    return filter_class


def _get_filter_type_for_field(
    field_type: type, parent_class: type | None = None, field_name: str | None = None
) -> type:
    """Get the appropriate filter type for a field type."""
    # Handle Optional types FIRST before any other checks
    origin = get_origin(field_type)

    # For Python 3.10+, we need to check for UnionType as well
    import types

    if origin is Union or (hasattr(types, "UnionType") and isinstance(field_type, types.UnionType)):
        args = get_args(field_type)
        # Filter out None type
        non_none_types = [arg for arg in args if arg is not type(None)]
        if non_none_types:
            field_type = non_none_types[0]
            origin = get_origin(field_type)

    # Check for full-text search fields by name (before type checking)
    # This allows detecting tsvector fields which are usually str type in Python
    if field_name:
        field_lower = field_name.lower()
        fulltext_patterns = [
            "search_vector",
            "searchvector",
            "tsvector",
            "ts_vector",
            "fulltext_vector",
            "fulltextvector",
            "text_search",
            "textsearch",
            "search_index",
            "searchindex",
        ]
        if any(pattern in field_lower for pattern in fulltext_patterns):
            return FullTextFilter

    # Check for vector/embedding fields by name pattern (BEFORE list type checking)
    # This allows list[float] to map to VectorFilter for embeddings
    if field_name:
        field_lower = field_name.lower()
        vector_patterns = [
            "embedding",
            "vector",
            "_embedding",
            "_vector",
            "embedding_vector",
            "embeddingvector",
            "text_embedding",
            "textembedding",
            "image_embedding",
            "imageembedding",
        ]
        # Check if it's a vector field (pattern match + list type or vector field types)
        if (origin is list and any(pattern in field_lower for pattern in vector_patterns)) or (
            field_type in (HalfVectorField, SparseVectorField, QuantizedVectorField)
        ):
            return VectorFilter

    # Check if it's a List type
    if origin is list:
        # Use ArrayFilter for list/array fields
        return ArrayFilter

    # Check if this is a FraiseQL type (nested object)
    if hasattr(field_type, "__fraiseql_definition__"):
        # Check cache first
        if field_type in _where_input_cache:
            return _where_input_cache[field_type]

        # Check for circular reference
        if field_type in _generation_stack:
            # For circular references, we'll use a placeholder that will be resolved later
            # Store the deferred type for later resolution
            return type(f"_Deferred_{field_type.__name__}WhereInput", (), {})

        # PHASE 2 ENHANCEMENT: Check if type has auto-generated WhereInput property
        # This allows lazy properties to handle nested types naturally
        if hasattr(field_type, "WhereInput"):
            try:
                # Use the lazy property - it will generate on access
                # This breaks circular dependencies naturally
                nested_where_input = field_type.WhereInput
                return nested_where_input
            except Exception:
                # If lazy property fails, fall through to manual generation
                pass

        # Generate nested where input type recursively
        # Since we're already inside the module, we can call the function directly
        # without circular import issues
        nested_where_input = create_graphql_where_input(field_type)
        return nested_where_input

    # First check for FraiseQL scalar types that need restricted filters
    # Import at runtime to avoid circular imports
    try:
        from fraiseql.types import CIDR, DateTime, IpAddress, LTree, MacAddress
        from fraiseql.types.scalars.daterange import DateRangeField

        exotic_type_mapping = {
            IpAddress: NetworkAddressFilter,
            CIDR: NetworkAddressFilter,
            MacAddress: MacAddressFilter,
            LTree: LTreeFilter,
            DateTime: DateTimeFilter,  # Use existing DateTimeFilter for FraiseQL DateTime
            DateRangeField: DateRangeFilter,
        }

        # Check if this is one of our exotic scalar types
        if field_type in exotic_type_mapping:
            return exotic_type_mapping[field_type]

    except ImportError:
        # FraiseQL scalar types not available, continue with standard mapping
        pass

    # Map Python types to filter types
    # ID type always uses IDFilter (GraphQL ID scalar) regardless of policy.
    # This keeps GraphQL schema consistent with frontend expectations ($id: ID!).
    # UUID validation (if IDPolicy.UUID) happens at runtime, not at schema level.
    type_mapping = {
        str: StringFilter,
        int: IntFilter,
        float: FloatFilter,
        Decimal: DecimalFilter,
        bool: BooleanFilter,
        UUID: UUIDFilter,
        ID: IDFilter,  # Always use IDFilter - UUID validation is runtime
        date: DateFilter,
        datetime: DateTimeFilter,
        dict: JSONBFilter,  # JSONB fields are typically dict type in Python
    }

    # Check for GraphQL scalar types that should use specialized filters
    # These need to be checked before the generic GraphQLScalarType handling
    if isinstance(field_type, GraphQLScalarType):
        try:
            from fraiseql.types.scalars import (
                CIDRScalar,
                IpAddressScalar,
                LTreeScalar,
                MacAddressScalar,
            )

            graphql_scalar_mapping = {
                IpAddressScalar: NetworkAddressFilter,
                CIDRScalar: NetworkAddressFilter,
                MacAddressScalar: MacAddressFilter,
                LTreeScalar: LTreeFilter,
            }

            if field_type in graphql_scalar_mapping:
                return graphql_scalar_mapping[field_type]
        except ImportError:
            pass

        # Fall back to generic custom scalar filter
        return _create_custom_scalar_filter(field_type)

    return type_mapping.get(field_type, StringFilter)  # Default to StringFilter


def _convert_filter_to_dict(filter_obj: Any) -> dict[str, Any]:
    """Convert a filter object to a dictionary for SQL where type."""
    if filter_obj is None:
        return {}

    # Check if this is already a plain dict - return it directly
    if isinstance(filter_obj, dict):
        return filter_obj

    # Check if this is a nested where input (has _target_class and _to_sql_where)
    if hasattr(filter_obj, "_target_class") and hasattr(filter_obj, "_to_sql_where"):
        # This is a nested where input, convert it recursively
        nested_where = filter_obj._to_sql_where()
        return {"__nested__": nested_where}

    result = {}
    # Check if it's a FraiseQL type with __gql_fields__
    if hasattr(filter_obj, "__gql_fields__"):
        # Map long names to short names for array operators
        ARRAY_OPERATOR_ALIASES = {
            "array_eq": "eq",
            "array_neq": "neq",
            "array_contains": "contains",
            "array_contained_by": "contained_by",
            "array_overlaps": "overlaps",
            "array_length_eq": "len_eq",
            "array_length_gt": "len_gt",
            "array_length_gte": "len_gte",
            "array_length_lt": "len_lt",
            "array_any_eq": "any_eq",
            "array_all_eq": "all_eq",
        }

        for field_name in filter_obj.__gql_fields__:
            value = getattr(filter_obj, field_name)
            if value is not None:
                # Handle 'in_' field mapping to 'in'
                if field_name == "in_":
                    result["in"] = value
                else:
                    # Map long names to short names
                    normalized_field = ARRAY_OPERATOR_ALIASES.get(field_name, field_name)
                    result[normalized_field] = value
    # Fallback for regular objects - use __dict__
    elif hasattr(filter_obj, "__dict__"):
        # Map long names to short names for array operators
        ARRAY_OPERATOR_ALIASES = {
            "array_eq": "eq",
            "array_neq": "neq",
            "array_contains": "contains",
            "array_contained_by": "contained_by",
            "array_overlaps": "overlaps",
            "array_length_eq": "len_eq",
            "array_length_gt": "len_gt",
            "array_length_gte": "len_gte",
            "array_length_lt": "len_lt",
            "array_any_eq": "any_eq",
            "array_all_eq": "all_eq",
        }

        for field_name, value in filter_obj.__dict__.items():
            if value is not None:
                # Handle 'in_' field mapping to 'in'
                if field_name == "in_":
                    result["in"] = value
                else:
                    # Map long names to short names
                    normalized_field = ARRAY_OPERATOR_ALIASES.get(field_name, field_name)
                    result[normalized_field] = value

    return result


def _convert_graphql_input_to_where_type(graphql_input: Any, target_class: type) -> Any:
    """Convert a GraphQL where input to SQL where type."""
    if graphql_input is None:
        return None

    # Create SQL where type
    SqlWhereType = safe_create_where_type(target_class)
    where_obj = SqlWhereType()

    # Convert each field
    # Check if it's a FraiseQL type with __gql_fields__
    if hasattr(graphql_input, "__gql_fields__"):
        for field_name in graphql_input.__gql_fields__:
            filter_value = getattr(graphql_input, field_name)
            if filter_value is not None:
                # Handle logical operators specially
                if field_name in ("OR", "AND"):
                    # These are lists of WhereInput objects or dicts
                    if isinstance(filter_value, list):
                        converted_list = []
                        for item in filter_value:
                            if hasattr(item, "_to_sql_where"):
                                # WhereInput object
                                converted_list.append(item._to_sql_where())
                            elif isinstance(item, dict):
                                # Plain dict - convert it recursively
                                converted_list.append(item)
                        setattr(where_obj, field_name, converted_list)
                elif field_name == "NOT":
                    # This is a single WhereInput object
                    if hasattr(filter_value, "_to_sql_where"):
                        setattr(where_obj, field_name, filter_value._to_sql_where())
                # Check if this is a nested where input
                elif hasattr(filter_value, "_target_class") and hasattr(
                    filter_value, "_to_sql_where"
                ):
                    # Convert nested where input recursively
                    nested_where = filter_value._to_sql_where()
                    setattr(where_obj, field_name, nested_where)
                else:
                    # Convert filter object to operator dict
                    operator_dict = _convert_filter_to_dict(filter_value)
                    if operator_dict:
                        setattr(where_obj, field_name, operator_dict)
                    else:
                        # If the filter is empty, set to None instead of empty dict
                        setattr(where_obj, field_name, None)
    # Fallback for regular objects
    elif hasattr(graphql_input, "__dict__"):
        for field_name, filter_value in graphql_input.__dict__.items():
            if filter_value is not None:
                # Handle logical operators specially
                if field_name in ("OR", "AND"):
                    # These are lists of WhereInput objects or dicts
                    if isinstance(filter_value, list):
                        converted_list = []
                        for item in filter_value:
                            if hasattr(item, "_to_sql_where"):
                                # WhereInput object
                                converted_list.append(item._to_sql_where())
                            elif isinstance(item, dict):
                                # Plain dict - convert it recursively
                                converted_list.append(item)
                        setattr(where_obj, field_name, converted_list)
                elif field_name == "NOT":
                    # This is a single WhereInput object
                    if hasattr(filter_value, "_to_sql_where"):
                        setattr(where_obj, field_name, filter_value._to_sql_where())
                # Check if this is a nested where input
                elif hasattr(filter_value, "_target_class") and hasattr(
                    filter_value, "_to_sql_where"
                ):
                    # Convert nested where input recursively
                    nested_where = filter_value._to_sql_where()
                    setattr(where_obj, field_name, nested_where)
                else:
                    # Convert filter object to operator dict
                    operator_dict = _convert_filter_to_dict(filter_value)
                    if operator_dict:
                        setattr(where_obj, field_name, operator_dict)
                    else:
                        # If the filter is empty, set to None instead of empty dict
                        setattr(where_obj, field_name, None)

    return where_obj


def create_graphql_where_input(cls: type, name: str | None = None) -> type:
    """Create a GraphQL-compatible where input type with operator filters.

    Args:
        cls: The dataclass or fraise_type to generate filters for
        name: Optional name for the generated input type (defaults to {ClassName}WhereInput)

    Returns:
        A new dataclass decorated with @fraise_input that supports operator-based filtering

    Example:
        ```python
        @fraise_type
        class User:
            id: UUID
            name: str
            age: int
            is_active: bool

        UserWhereInput = create_graphql_where_input(User)

        # Usage in resolver
        @fraiseql.query
        async def users(info, where: UserWhereInput | None = None) -> list[User]:
            return await info.context["db"].find("user_view", where=where)
        ```
    """
    # Check cache first (only for unnamed types to allow custom names)
    if name is None and cls in _where_input_cache:
        return _where_input_cache[cls]

    # Add to generation stack to detect circular references
    _generation_stack.add(cls)

    def _is_fraise_type(field_type: Any) -> bool:
        """Check if a type is a FraiseQL type (has __fraiseql_definition__)."""
        return hasattr(field_type, "__fraiseql_definition__")

    try:
        # Get type hints from the class
        try:
            type_hints = get_type_hints(cls)
        except Exception:
            # Fallback for classes that might not have proper annotations
            type_hints = {}
            for key, value in cls.__annotations__.items():
                type_hints[key] = value

        # Generate field definitions for the input type
        field_definitions = []
        field_defaults = {}
        deferred_fields = {}  # For circular references

        for field_name, field_type in type_hints.items():
            # Skip private fields
            if field_name.startswith("_"):
                continue

            # Get the appropriate filter type
            filter_type = _get_filter_type_for_field(
                field_type, parent_class=cls, field_name=field_name
            )

            # Check if this is a deferred type (circular reference)
            if hasattr(filter_type, "__name__") and filter_type.__name__.startswith("_Deferred_"):
                # Store for later resolution
                deferred_fields[field_name] = field_type
                # Use StringFilter as temporary placeholder
                filter_type = StringFilter

            # Add as optional field
            field_definitions.append((field_name, Optional[filter_type], None))
            field_defaults[field_name] = None

        # Generate class name
        class_name = name or f"{cls.__name__}WhereInput"

        # Add logical operators fields using safer types for GraphQL schema generation
        # These will work at runtime but won't break GraphQL type conversion
        logical_fields = [
            ("OR", Optional[list], None),
            ("AND", Optional[list], None),
            (
                "NOT",
                Optional[dict],
                None,
            ),  # Use dict instead of object for better GraphQL compatibility
        ]

        # Add logical operators to field definitions
        field_definitions.extend(logical_fields)
        field_defaults.update({field_name: default for field_name, _, default in logical_fields})

        # Create the dataclass
        WhereInputClass = make_dataclass(
            class_name,
            field_definitions,
            bases=(),
            frozen=False,
        )

        # Add the fraise_input decorator
        WhereInputClass = fraise_input(WhereInputClass)

        # Cache before processing deferred fields (only for unnamed types)
        if name is None:
            _where_input_cache[cls] = WhereInputClass

        # Process deferred fields (circular references)
        for field_name, field_type in deferred_fields.items():
            # Now that we're cached, try to get the actual where input type
            if hasattr(field_type, "__fraiseql_definition__") and field_type in _where_input_cache:
                # Update the field annotation
                WhereInputClass.__annotations__[field_name] = Optional[
                    _where_input_cache[field_type]
                ]
                # Update the dataclass field
                if hasattr(WhereInputClass, "__dataclass_fields__"):
                    # Update the type in place to preserve the Field's internal attributes
                    existing_field = WhereInputClass.__dataclass_fields__.get(field_name)
                    if existing_field is not None:
                        existing_field.type = Optional[_where_input_cache[field_type]]

        # Update AND/OR field types to use self-referential WhereInput type
        # This enables proper GraphQL schema generation for logical operators
        for logical_field in ("AND", "OR"):
            if logical_field in WhereInputClass.__annotations__:
                # The correct type for AND/OR is list of the WhereInput type itself
                self_ref_list_type = Optional[list[WhereInputClass]]

                # Update annotation
                WhereInputClass.__annotations__[logical_field] = self_ref_list_type

                # Update __gql_type_hints__ (used by GraphQL type converter)
                if hasattr(WhereInputClass, "__gql_type_hints__"):
                    WhereInputClass.__gql_type_hints__[logical_field] = self_ref_list_type

                # Update __gql_fields__ (used by GraphQL type converter)
                if hasattr(WhereInputClass, "__gql_fields__"):
                    from fraiseql.fields import fraise_field

                    # Create a FraiseQLField with the correct type
                    gql_field = fraise_field(default=None)
                    gql_field.name = logical_field
                    gql_field.field_type = self_ref_list_type
                    WhereInputClass.__gql_fields__[logical_field] = gql_field

                # Update dataclass field type - only update the type attribute
                # to preserve the Field's internal _field_type attribute needed by asdict()
                if hasattr(WhereInputClass, "__dataclass_fields__"):
                    existing_field = WhereInputClass.__dataclass_fields__.get(logical_field)
                    if existing_field is not None:
                        # Update the type in place - don't replace the entire field
                        existing_field.type = self_ref_list_type

        # Add conversion method
        WhereInputClass._target_class = cls
        WhereInputClass._to_sql_where = lambda self: _convert_graphql_input_to_where_type(self, cls)

        # Add dict conversion method for normalization
        def _to_whereinput_dict(self: Any) -> dict[str, Any]:
            """Convert WhereInput to normalized dict format.

            This method recursively extracts all filter values from the WhereInput
            object and its nested objects/filters, converting them to a plain dict
            structure that can be normalized to WhereClause.

            Returns:
                Dict representation with filter operators extracted

            Examples:
                # WhereInput with UUIDFilter
                AllocationWhereInput(
                    machine=MachineWhereInput(
                        id=UUIDFilter(eq=UUID("123"))
                    )
                )._to_whereinput_dict()

                # Returns:
                {
                    "machine": {
                        "id": {
                            "eq": UUID("123")
                        }
                    }
                }
            """
            result = {}

            for field_name, field_value in self.__dict__.items():
                # Skip None values and private fields
                if field_value is None or field_name.startswith("_"):
                    continue

                # Handle logical operators (OR, AND, NOT)
                if field_name in ("OR", "AND", "NOT"):
                    if field_name in ("OR", "AND") and isinstance(field_value, list):
                        # OR/AND: list of WhereInput objects
                        result[field_name] = [
                            item._to_whereinput_dict()
                            if hasattr(item, "_to_whereinput_dict")
                            else item
                            for item in field_value
                        ]
                    elif field_name == "NOT" and hasattr(field_value, "_to_whereinput_dict"):
                        # NOT: single WhereInput object
                        result[field_name] = field_value._to_whereinput_dict()
                    else:
                        result[field_name] = field_value
                    continue

                # Handle nested WhereInput objects
                if hasattr(field_value, "_to_whereinput_dict"):
                    nested_dict = field_value._to_whereinput_dict()
                    if nested_dict:
                        result[field_name] = nested_dict
                # Handle Filter objects (UUIDFilter, StringFilter, etc.)
                elif hasattr(field_value, "__dict__") and _is_filter_object(field_value):
                    # Extract non-None operators from filter
                    filter_dict = {
                        op: val
                        for op, val in field_value.__dict__.items()
                        if val is not None and not op.startswith("_")
                    }
                    if filter_dict:
                        result[field_name] = filter_dict
                # Handle plain dicts
                elif isinstance(field_value, dict):
                    result[field_name] = field_value
                # Handle scalar values
                elif isinstance(field_value, (str, int, float, bool, UUID, date, datetime)):
                    result[field_name] = {"eq": field_value}

            return result

        def _is_filter_object(obj: Any) -> bool:
            """Check if object is a Filter type (has operator fields)."""
            if not hasattr(obj, "__dict__"):
                return False

            # Filter objects have operator fields
            operator_fields = {
                "eq",
                "neq",
                "in_",
                "nin",
                "gt",
                "gte",
                "lt",
                "lte",
                "contains",
                "icontains",
                "startswith",
                "endswith",
                "istartswith",
                "iendswith",
                "isnull",
                "matches",
                "imatches",
                "not_matches",
            }
            obj_fields = set(obj.__dict__.keys())

            # If it has at least one operator field, it's a Filter
            return bool(operator_fields & obj_fields)

        WhereInputClass._to_whereinput_dict = _to_whereinput_dict

        # Get FK relationships from metadata
        from fraiseql.db import _table_metadata

        sql_source = getattr(cls, "__sql_source__", None) or getattr(cls, "_table_name", None)
        fk_relationships = {}

        if sql_source and sql_source in _table_metadata:
            fk_relationships = _table_metadata[sql_source].get("fk_relationships", {})

        # Attach metadata to class
        WhereInputClass.__table_name__ = sql_source
        WhereInputClass.__fk_relationships__ = fk_relationships

        # Validate FK relationships at generation time
        if sql_source and sql_source in _table_metadata:
            metadata = _table_metadata[sql_source]
            table_columns = metadata.get("columns", set())

            # Validate declared FKs exist
            for field_name, fk_column in fk_relationships.items():
                if table_columns and fk_column not in table_columns:
                    logger.warning(
                        f"FK relationship {field_name} → {fk_column} declared "
                        f"but {fk_column} not in registered columns for {sql_source}"
                    )

            # Check for undeclared FK candidates
            type_hints = get_type_hints(cls)
            for field_name, field_type in type_hints.items():
                if _is_fraise_type(field_type):
                    potential_fk = f"{field_name}_id"
                    if (
                        field_name not in fk_relationships
                        and table_columns
                        and potential_fk in table_columns
                    ):
                        logger.info(
                            f"Field {cls.__name__}.{field_name} looks like FK relationship "
                            f"(column {potential_fk} exists) but not declared in fk_relationships. "
                            f"Using convention-based detection."
                        )

        # Add helpful docstring with FK info
        docstring = f"GraphQL where input type for {cls.__name__} with operator-based filtering."

        if fk_relationships:
            fk_doc = "\n".join(
                f"    - {field} → FK column '{col}'" for field, col in fk_relationships.items()
            )
            docstring += f"\n\nFK Relationships:\n{fk_doc}"

        WhereInputClass.__doc__ = docstring

        return WhereInputClass

    finally:
        # Remove from generation stack
        _generation_stack.discard(cls)

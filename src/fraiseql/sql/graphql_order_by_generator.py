"""GraphQL-compatible order by input type generator.

This module provides utilities to dynamically generate GraphQL input types
for ordering. These types can be used directly in GraphQL resolvers and are
automatically converted to SQL ORDER BY clauses.
"""

import warnings
from dataclasses import make_dataclass
from functools import lru_cache
from typing import Any, Optional, TypeVar, Union, get_args, get_origin, get_type_hints

from fraiseql import fraise_input
from fraiseql.sql.order_by_generator import (
    VECTOR_DISTANCE_OPERATORS,
    OrderBy,
    OrderBySet,
    OrderDirection,
)
from fraiseql.types.scalars.vector import HalfVectorField, QuantizedVectorField, SparseVectorField

# Type variable for generic types
T = TypeVar("T")

# Cache for generated order by input types to handle circular references
_order_by_input_cache: dict[type, type] = {}
# Stack to track types being generated to detect circular references
_generation_stack: set[type] = set()


# Import OrderDirection from order_by_generator


@fraise_input
class VectorOrderBy:
    """Order by input for vector/embedding fields using pgvector distance operators.

    Allows ordering query results by vector similarity/distance using PostgreSQL
    pgvector operators. Distance values are returned raw from PostgreSQL.

    Fields:
        cosine_distance: Order by cosine distance (accepts dense or sparse vectors)
        l2_distance: Order by L2/Euclidean distance (accepts dense or sparse vectors)
        l1_distance: Order by L1/Manhattan distance (accepts dense or sparse vectors)
        inner_product: Order by negative inner product (accepts dense or sparse vectors)
        hamming_distance: Order by Hamming distance for bit vectors
        jaccard_distance: Order by Jaccard distance for bit vectors

    Example:
        orderBy: { embedding: { l1_distance: [0.1, 0.2, 0.3] } }
        orderBy: {
            sparse_embedding: { cosine_distance: { indices: [1,3,5], values: [0.1,0.2,0.3] } }
        }
        orderBy: { fingerprint: { hamming_distance: "101010" } }
        # Orders by distance to the given vector (ASC = most similar first)
    """

    cosine_distance: list[float] | dict[str, Any] | None = None
    l2_distance: list[float] | dict[str, Any] | None = None
    l1_distance: list[float] | dict[str, Any] | None = None
    inner_product: list[float] | dict[str, Any] | None = None
    custom_distance: dict[str, Any] | None = (
        None  # {function: "my_distance_func", parameters: [...]}
    )
    vector_norm: Any | None = None  # For norm calculations
    hamming_distance: str | None = None  # bit string like "101010"
    jaccard_distance: str | None = None  # bit string like "111000"


@fraise_input
class OrderByItem:
    """Single order by instruction with optional collation.

    Attributes:
        field: Field name to sort by
        direction: Sort direction (ASC or DESC)
        collation: Optional PostgreSQL collation for text sorting
                   - Explicit value: Use this collation
                   - None: Use global default (if configured)
                   - null in GraphQL: Skip global default

    Examples:
        OrderByItem(field="name", direction=ASC)  # Uses global default
        OrderByItem(field="name", direction=ASC, collation="fr_FR.utf8")  # Override
        OrderByItem(field="id", direction=ASC, collation=None)  # Skip collation
    """

    field: str
    direction: OrderDirection = OrderDirection.ASC
    collation: str | None = None


def _is_fraiseql_type(field_type: type) -> bool:
    """Check if a type is a FraiseQL type (has __fraiseql_definition__)."""
    # Handle Optional types first
    origin = get_origin(field_type)

    # For Python 3.10+, we need to check for UnionType as well
    import types

    if origin is Union or (hasattr(types, "UnionType") and isinstance(field_type, types.UnionType)):
        args = get_args(field_type)
        # Filter out None type
        non_none_types = [arg for arg in args if arg is not type(None)]
        if non_none_types:
            field_type = non_none_types[0]
            # Re-check origin after unwrapping
            origin = get_origin(field_type)

    # Don't consider list types as FraiseQL types
    if origin is list:
        return False

    return hasattr(field_type, "__fraiseql_definition__")


def _normalize_order_direction(direction: Any) -> OrderDirection:
    """Convert various direction inputs to OrderDirection enum."""
    if isinstance(direction, OrderDirection):
        return direction
    if hasattr(direction, "value"):  # Enum-like
        return OrderDirection.ASC if direction.value == "asc" else OrderDirection.DESC
    if isinstance(direction, str):
        return OrderDirection.ASC if direction.upper() == "ASC" else OrderDirection.DESC
    return OrderDirection.ASC  # Default


def _unwrap_annotation(annotation: Any, *, into_list: bool) -> Any:
    """Strip ``| None`` to reach the annotation that carries a type.

    ``into_list`` also steps inside ``list[X]``. That is right while *walking*
    a dotted path — ``posts.title`` has to reach ``Post`` through
    ``list[Post]`` — and wrong at the leaf, where ``list[str]`` is an array and
    not a text field: sorting by one collates the serialized JSON array, which
    is meaningless rather than merely useless.
    """
    import types as _types

    origin = get_origin(annotation)
    if origin is Union or (
        hasattr(_types, "UnionType") and isinstance(annotation, _types.UnionType)
    ):
        non_none = [arg for arg in get_args(annotation) if arg is not type(None)]
        if not non_none:
            return None
        return _unwrap_annotation(non_none[0], into_list=into_list)

    if into_list and origin is list:
        args = get_args(annotation)
        return _unwrap_annotation(args[0], into_list=into_list) if args else None

    return annotation


@lru_cache(maxsize=2048)
def _resolve_field_type(source_type: Any, path: tuple[str, ...]) -> Any | None:
    """Walk a dotted sort path through ``source_type``'s annotations.

    Returns the annotation the leaf segment names, or ``None`` when any segment
    cannot be resolved — an unregistered view, a container like the aggregation
    ``dimensions`` prefix that is not a declared field, or a class whose hints
    do not evaluate. ``None`` is the answer that leaves the collation alone, so
    every unknown is conservative by construction.
    """
    current: Any = source_type
    last = len(path) - 1
    for index, segment in enumerate(path):
        if current is None or not isinstance(current, type):
            return None
        try:
            hints = get_type_hints(current)
        except Exception:
            return None
        annotation = hints.get(segment)
        if annotation is None:
            return None
        current = _unwrap_annotation(annotation, into_list=index < last)
    return current


def _is_text_field(source_type: Any, dotted_path: str) -> bool:
    """Whether a sort key names a field the database will hold as text.

    Only ``str`` counts. The global default exists to make text sort by locale,
    and a collation on anything else is either a silent wrong answer (a numeric
    JSONB field sorts 1, 10, 2) or an outright error ("collations are not
    supported by type integer"). So the question is not "might this be text" but
    "is this certainly text", and everything unresolved answers no (#482).
    """
    if source_type is None:
        return False
    return _resolve_field_type(source_type, tuple(dotted_path.split("."))) is str


def _source_type_of(order_by_input: Any) -> Any | None:
    """The type a generated order-by input was built for, if this is one."""
    return getattr(type(order_by_input), "_target_class", None)


def _apply_collation_default(
    field_collation: str | None,
    global_collation: str | None,
    was_explicitly_set: bool = False,
    is_text_field: bool = False,
) -> str | None:
    """Resolve the collation for one sort key. The single place that decides.

    Precedence:
    1. Per-field explicit value, including an explicit None
    2. ``default_string_collation`` from config, on text fields only
    3. Nothing -- the database default

    Why the default is restricted to text
    -------------------------------------
    ``default_string_collation`` is documented as applying to "all *text*
    fields". Nothing in the order_by pipeline tracked which fields were text, so
    it was applied to every field, numeric ones included. That was harmless only
    while a collation never reached the sort; since #476 one does, and a blanket
    default would

    * make a numeric JSONB sort lexicographic -- 1, 10, 2 -- silently, and
    * make a numeric flat column fail with "collations are not supported by
      type integer".

    So #481 dropped the default rather than ship either, and #482 supplies what
    was missing: ``is_text_field``, resolved from the view's registered type by
    :func:`_is_text_field`. Anything that cannot be resolved to ``str`` answers
    False, so an unknown field keeps the behaviour it has had all along.

    Args:
        field_collation: Collation from field/input
        global_collation: Global default from config
        was_explicitly_set: True if field_collation was explicitly set
                           (even if set to None)
        is_text_field: True only when the sort key is known to name a text field

    Returns:
        Collation to use, or None for database default

    Examples:
        # Explicit per-field value wins over the default
        _apply_collation_default("en_US.utf8", "fr_FR.utf8", True, True) -> "en_US.utf8"

        # Explicit None wins too: it asks for the database default
        _apply_collation_default(None, "fr_FR.utf8", True, True) -> None

        # No field value, text field: the global default applies
        _apply_collation_default(None, "fr_FR.utf8", False, True) -> "fr_FR.utf8"

        # No field value, not known to be text: left alone
        _apply_collation_default(None, "fr_FR.utf8", False, False) -> None

        # No field value, no global default
        _apply_collation_default(None, None, False, True) -> None
    """
    # A collation the caller asked for on this field always wins.
    if was_explicitly_set:
        return field_collation

    if is_text_field:
        return global_collation

    return None


def _is_vector_order_by(value: Any) -> bool:
    """Recognise a ``VectorOrderBy`` without importing it into the check."""
    return hasattr(value, "__gql_fields__") and hasattr(value, "cosine_distance")


def _append_vector_order_by(value: Any, field_path: str, instructions: list[OrderBy]) -> None:
    """Append the one distance instruction a ``VectorOrderBy`` asks for.

    Both ``order_by`` shapes route through here. They had a copy each until
    #483 and emitted different subsets of ``VECTOR_DISTANCE_OPERATORS``, so the
    same request sorted differently -- or not at all -- depending on which shape
    it arrived in.
    """
    for operator in VECTOR_DISTANCE_OPERATORS:
        operand = getattr(value, operator, None)
        if operand is not None:
            instructions.append(
                OrderBy(
                    field=f"{field_path}.{operator}",
                    direction=OrderDirection.ASC,  # ASC = nearest first
                    value=operand,
                )
            )
            return


def _collect_dict_order_by(
    obj_dict: dict[str, Any],
    instructions: list[OrderBy],
    prefix: str = "",
    global_collation: str | None = None,
    source_type: Any = None,
) -> None:
    """Walk a dict-shaped ``order_by``, appending one ``OrderBy`` per leaf.

    The recursion is the point. ``{"measures": {"cost": "desc"}}`` has to reach
    ``measures.cost DESC``; the list-of-dicts branch used to parse dicts with its
    own shallower loop, which handed a nested dict to
    :func:`_normalize_order_direction`, got the ASC default back, and sorted by
    the wrong field in the wrong direction without a word (#475).

    One parser now serves both dict shapes, so ``{...}`` and ``[{...}]`` cannot
    drift apart again.
    """
    from fraiseql.utils.casing import to_snake_case

    for field_name, value in obj_dict.items():
        if value is None:
            continue

        snake_field_name = to_snake_case(field_name)
        field_path = f"{prefix}.{snake_field_name}" if prefix else snake_field_name

        # Nested object: recurse so the leaf carries the full dotted path.
        if isinstance(value, dict):
            _collect_dict_order_by(value, instructions, field_path, global_collation, source_type)
        # A VectorOrderBy names the distance operator it wants.
        elif _is_vector_order_by(value):
            _append_vector_order_by(value, field_path, instructions)
        # A direction: a string, an OrderDirection, or any enum-like carrying one.
        elif isinstance(value, (OrderDirection, str)) or hasattr(value, "value"):
            # A dict carries no per-field collation, so only the configured
            # default can apply here, and only to a field known to be text.
            collation = _apply_collation_default(
                None,
                global_collation,
                False,
                _is_text_field(source_type, field_path),
            )
            instructions.append(
                OrderBy(
                    field=field_path,
                    direction=_normalize_order_direction(value),
                    collation=collation,
                )
            )
        else:
            # Defaulting to ASC here would mean "sorted by something else
            # entirely", silently. Say so and drop the key instead.
            warnings.warn(
                f"order_by: ignoring {field_path!r} - cannot read a sort direction from "
                f"{type(value).__name__}. Expected a direction, a nested dict, or None.",
                UserWarning,
                stacklevel=3,
            )


def _convert_order_by_input_to_sql(
    order_by_input: Any, config: Any = None, source_type: Any = None
) -> OrderBySet | None:
    """Convert GraphQL order by input to SQL OrderBySet with optional collation.

    Args:
        order_by_input: GraphQL OrderBy input (various formats)
        config: Optional FraiseQLConfig with default_string_collation
        source_type: The type the sort paths are rooted in, used to decide which
            fields are text so ``default_string_collation`` can apply to those
            and nothing else (#482). A generated order-by input names its own
            source type, so this only has to be supplied for the dict and list
            shapes, which carry field names and nothing more. Omitted, the
            configured default simply does not apply -- the behaviour every
            shape had before.

    Returns:
        OrderBySet with collation applied per precedence rules
    """
    if order_by_input is None:
        return None

    if source_type is None:
        source_type = _source_type_of(order_by_input)

    global_collation = config.default_string_collation if config else None
    instructions = []

    # Handle single OrderByItem
    if hasattr(order_by_input, "field") and hasattr(order_by_input, "direction"):
        direction = _normalize_order_direction(order_by_input.direction)

        # Apply collation with precedence
        field_collation = getattr(order_by_input, "collation", None)
        was_explicit = hasattr(order_by_input, "collation")
        collation = _apply_collation_default(
            field_collation,
            global_collation,
            was_explicit,
            _is_text_field(source_type, order_by_input.field),
        )

        instructions.append(
            OrderBy(field=order_by_input.field, direction=direction, collation=collation)
        )
        return OrderBySet(instructions=instructions)

    # Handle list of OrderByItem or list of dicts
    if isinstance(order_by_input, list):
        for item in order_by_input:
            # Handle OrderByItem objects
            if hasattr(item, "field") and hasattr(item, "direction"):
                direction = _normalize_order_direction(item.direction)

                # Apply collation with precedence
                field_collation = getattr(item, "collation", None)
                was_explicit = hasattr(item, "collation")
                collation = _apply_collation_default(
                    field_collation,
                    global_collation,
                    was_explicit,
                    _is_text_field(source_type, item.field),
                )

                instructions.append(
                    OrderBy(field=item.field, direction=direction, collation=collation)
                )
            # Handle dictionary items like {'ipAddress': 'asc'}, which may nest.
            # A dict carries no per-field collation, so none is set -- see
            # _apply_collation_default.
            elif isinstance(item, dict):
                _collect_dict_order_by(item, instructions, "", global_collation, source_type)
        return OrderBySet(instructions=instructions) if instructions else None

    # Handle object with field-specific order directions
    if hasattr(order_by_input, "__gql_fields__"):

        def process_order_by(obj: Any, prefix: str = "") -> None:
            """Recursively process order by object."""
            for field_name in obj.__gql_fields__:
                value = getattr(obj, field_name)
                if value is not None:
                    field_path = f"{prefix}.{field_name}" if prefix else field_name
                    # A VectorOrderBy names the distance operator it wants.
                    #
                    # This has to be chained with the direction/recursion cases
                    # below rather than standing alone: a VectorOrderBy carries
                    # __gql_fields__, so an unchained check fell through to the
                    # nested-input recursion as well, which read the bit string
                    # of hamming_distance / jaccard_distance as a direction --
                    # any string that is not "ASC" normalises to DESC -- and
                    # appended a contradictory second instruction (#483).
                    if _is_vector_order_by(value):
                        _append_vector_order_by(value, field_path, instructions)
                    # If it's an OrderDirection enum or string, use it
                    elif isinstance(value, (OrderDirection, str)):
                        direction = _normalize_order_direction(value)

                        # No per-field override in this format, so only the
                        # configured default can apply -- see
                        # _apply_collation_default.
                        collation = _apply_collation_default(
                            None,
                            global_collation,
                            False,
                            _is_text_field(source_type, field_path),
                        )

                        instructions.append(
                            OrderBy(field=field_path, direction=direction, collation=collation)
                        )
                    # If it's a nested order by input, process recursively
                    elif hasattr(value, "__gql_fields__"):
                        process_order_by(value, field_path)

        process_order_by(order_by_input)

    # Handle plain dict (common from GraphQL frameworks)
    elif isinstance(order_by_input, dict):
        _collect_dict_order_by(order_by_input, instructions, "", global_collation, source_type)

    return OrderBySet(instructions=instructions) if instructions else None


def create_graphql_order_by_input(cls: type, name: str | None = None) -> type:
    """Create a GraphQL-compatible order by input type.

    This generates an input type where each field can be set to an OrderDirection
    to specify sorting. For nested objects, it creates nested order by inputs.

    Args:
        cls: The dataclass or fraise_type to generate order by fields for
        name: Optional name for the generated input type (defaults to {ClassName}OrderByInput)

    Returns:
        A new dataclass decorated with @fraise_input that supports field-based ordering

    Example:
        ```python
        @fraise_type
        class User:
            id: UUID
            name: str
            age: int
            created_at: datetime

        UserOrderByInput = create_graphql_order_by_input(User)

        # Usage in resolver
        @fraiseql.query
        async def users(info, order_by: UserOrderByInput | None = None) -> list[User]:
            return await info.context["db"].find("user_view", order_by=order_by)

        # GraphQL query
        query {
            users(orderBy: { name: ASC, createdAt: DESC }) {
                id
                name
            }
        }
        ```
    """
    # Handle case where cls might be a Union type
    origin = get_origin(cls)
    import types

    if origin is Union or (hasattr(types, "UnionType") and isinstance(cls, types.UnionType)):
        # Should not happen in normal usage
        raise TypeError(f"Cannot create order by input for Union type: {cls}")

    # Check cache first (only for unnamed types to allow custom names)
    if name is None and cls in _order_by_input_cache:
        return _order_by_input_cache[cls]

    # Add to generation stack to detect circular references
    _generation_stack.add(cls)

    try:
        # Get type hints from the class
        try:
            type_hints = get_type_hints(cls)
        except Exception:
            # Fallback for classes that might not have proper annotations
            type_hints = {}
            if hasattr(cls, "__annotations__"):
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

            # Check for vector/embedding fields by name pattern (BEFORE nested type check)
            # This allows list[float] to map to VectorOrderBy for embeddings
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
            if any(pattern in field_lower for pattern in vector_patterns):
                # Check if it's actually a list type or vector field types
                origin = get_origin(field_type)
                if origin is list or field_type in (
                    HalfVectorField,
                    SparseVectorField,
                    QuantizedVectorField,
                ):
                    field_definitions.append((field_name, Optional[VectorOrderBy], None))
                    field_defaults[field_name] = None
                    continue

            # Check if this is a nested FraiseQL type
            if _is_fraiseql_type(field_type):
                # Check cache first
                origin_type = field_type
                # Unwrap Optional
                origin = get_origin(field_type)
                import types as _types

                if origin is Union or (
                    hasattr(_types, "UnionType") and isinstance(field_type, _types.UnionType)
                ):
                    args = get_args(field_type)
                    non_none_types = [arg for arg in args if arg is not type(None)]
                    if non_none_types:
                        origin_type = non_none_types[0]

                if origin_type in _order_by_input_cache:
                    nested_order_by = _order_by_input_cache[origin_type]
                elif origin_type in _generation_stack:
                    # Circular reference - defer for later
                    deferred_fields[field_name] = origin_type
                    # Use OrderDirection as temporary placeholder
                    nested_order_by = OrderDirection
                else:
                    # Generate nested order by input recursively
                    # Make sure to pass the unwrapped type, not the Union
                    # Extra check to ensure we're not passing a Union type
                    import types as _types

                    if get_origin(origin_type) is Union or (
                        hasattr(_types, "UnionType") and isinstance(origin_type, _types.UnionType)
                    ):
                        # This shouldn't happen but let's be defensive
                        args = get_args(origin_type)
                        non_none_types = [arg for arg in args if arg is not type(None)]
                        if non_none_types:
                            origin_type = non_none_types[0]
                    nested_order_by = create_graphql_order_by_input(origin_type)

                field_definitions.append((field_name, Optional[nested_order_by], None))
            else:
                # For scalar fields, use OrderDirection
                field_definitions.append((field_name, Optional[OrderDirection], None))

            field_defaults[field_name] = None

        # Generate class name
        class_name = name or f"{cls.__name__}OrderByInput"

        # Create the dataclass
        OrderByInputClass = make_dataclass(
            class_name,
            field_definitions,
            bases=(),
            frozen=False,
        )

        # Add the fraise_input decorator
        OrderByInputClass = fraise_input(OrderByInputClass)

        # Cache before processing deferred fields (only for unnamed types)
        if name is None:
            _order_by_input_cache[cls] = OrderByInputClass

        # Process deferred fields (circular references)
        for field_name, field_type in deferred_fields.items():
            # Now that we're cached, try to get the actual order by input type
            if field_type in _order_by_input_cache:
                # Update the field annotation
                OrderByInputClass.__annotations__[field_name] = Optional[
                    _order_by_input_cache[field_type]
                ]
                # Update the dataclass field
                if hasattr(OrderByInputClass, "__dataclass_fields__"):
                    from dataclasses import MISSING, Field

                    field = Field(
                        default=None,
                        default_factory=MISSING,
                        init=True,
                        repr=True,
                        hash=None,
                        compare=True,
                        metadata={},
                    )
                    field.name = field_name
                    field.type = Optional[_order_by_input_cache[field_type]]
                    OrderByInputClass.__dataclass_fields__[field_name] = field

        # Add conversion method
        OrderByInputClass._target_class = cls
        OrderByInputClass._to_sql_order_by = lambda self, config=None: (
            _convert_order_by_input_to_sql(self, config)
        )

        # Add helpful docstring
        OrderByInputClass.__doc__ = (
            f"GraphQL order by input type for {cls.__name__} with field-based sorting."
        )

        return OrderByInputClass

    finally:
        # Remove from generation stack
        _generation_stack.discard(cls)


# Alternative approach: List-based ordering
def create_graphql_order_by_list_input(cls: type, name: str | None = None) -> type:
    """Create a GraphQL order by input that accepts a list of OrderByItem.

    This generates an input type that accepts a list of field/direction pairs,
    allowing for multiple sort criteria with explicit ordering.

    Args:
        cls: The dataclass or fraise_type to validate fields against
        name: Optional name for the generated input type

    Returns:
        A new list type that accepts OrderByItem instances

    Example:
        ```python
        @fraiseql.query
        async def users(info, order_by: list[OrderByItem] | None = None) -> list[User]:
            # Validates that field names exist in User type
            return await info.context["db"].find("user_view", order_by=order_by)

        # GraphQL query
        query {
            users(orderBy: [
                { field: "age", direction: DESC },
                { field: "name", direction: ASC }
            ]) {
                id
                name
            }
        }
        ```
    """
    # For list-based approach, we just return list[OrderByItem]
    # The validation would happen at runtime
    return list[OrderByItem]

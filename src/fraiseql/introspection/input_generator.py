"""Input type generation for AutoFraiseQL mutations.

This module provides utilities to generate GraphQL input types from PostgreSQL
function parameters for mutation generation.
"""

import logging
from typing import TYPE_CHECKING, Optional, Type

from .metadata_parser import MetadataParser, MutationAnnotation
from .postgres_introspector import FunctionMetadata, ParameterInfo
from .type_mapper import TypeMapper

if TYPE_CHECKING:
    from .postgres_introspector import PostgresIntrospector

logger = logging.getLogger(__name__)


class InputGenerator:
    """Generate GraphQL input types from PostgreSQL function parameters."""

    def __init__(self, type_mapper: TypeMapper):
        self.type_mapper = type_mapper
        self.metadata_parser = MetadataParser()

    def _find_jsonb_input_parameter(
        self, function_metadata: FunctionMetadata
    ) -> ParameterInfo | None:
        """Find the JSONB input parameter that maps to a composite type.

        SpecQL creates functions with this signature:
            app.create_contact(input_tenant_id UUID, input_user_id UUID, input_payload JSONB)

        We detect the 'input_payload JSONB' parameter.

        Args:
            function_metadata: Function metadata from introspection

        Returns:
            ParameterInfo if found, None otherwise

        Example:
            Function signature (created by SpecQL):
                app.create_contact(input_tenant_id UUID, input_user_id UUID, input_payload JSONB)

            Returns: ParameterInfo(name='input_payload', pg_type='jsonb', ...)
        """
        for param in function_metadata.parameters:
            # Check if parameter is JSONB and named 'input_payload'
            if param.pg_type.lower() == "jsonb" and param.name == "input_payload":
                return param

        return None

    def _extract_composite_type_name(
        self, function_metadata: FunctionMetadata, annotation: MutationAnnotation
    ) -> str | None:
        """Extract composite type name from annotation or convention.

        SpecQL follows a naming convention:
            Function: app.create_contact
            Composite type: app.type_create_contact_input

        We can either:
        1. Read explicit annotation (if SpecQL added it)
        2. Use naming convention to guess

        Priority:
        1. Explicit annotation: @fraiseql:mutation input_type=app.type_contact_input
        2. Convention: create_contact → type_create_contact_input

        Args:
            function_metadata: Function metadata
            annotation: Parsed mutation annotation

        Returns:
            Composite type name (without schema prefix) or None

        Example:
            function_name = "create_contact"
            → returns "type_create_contact_input"
        """
        # Priority 1: Check for explicit input_type in annotation (if SpecQL added it)
        if hasattr(annotation, "input_type") and annotation.input_type:
            # Extract type name from fully qualified name
            # "app.type_contact_input" → "type_contact_input"
            if "." in annotation.input_type:
                return annotation.input_type.split(".")[-1]
            return annotation.input_type

        # Priority 2: Convention-based extraction (SpecQL naming pattern)
        function_name = function_metadata.function_name

        # Convention: create_contact → type_create_contact_input
        return f"type_{function_name}_input"

    async def _generate_from_composite_type(
        self, composite_type_name: str, schema_name: str, introspector: "PostgresIntrospector"
    ) -> Type:
        """Generate input class from PostgreSQL composite type (created by SpecQL).

        This method READS the composite type from the database and generates
        a Python class. It does NOT create or modify the database.

        Steps:
        1. Introspect composite type to get attributes (READ from database)
        2. Parse field metadata from column comments (READ comments SpecQL created)
        3. Map PostgreSQL types to Python types
        4. Create input class with proper annotations

        Args:
            composite_type_name: Name of composite type (e.g., "type_create_contact_input")
            schema_name: Schema where function is defined (will check "app" for type)
            introspector: PostgresIntrospector instance

        Returns:
            Dynamically created input class

        Example:
            Composite type (created by SpecQL):
                CREATE TYPE app.type_create_contact_input AS (
                    email TEXT,
                    company_id UUID,
                    status TEXT
                );

            Generates Python class:
                class CreateContactInput:
                    email: str
                    companyId: UUID | None  # Note: camelCase from metadata
                    status: str
        """
        # Step 1: Introspect composite type (READ from database)
        composite_metadata = await introspector.discover_composite_type(
            composite_type_name, schema=schema_name
        )

        if not composite_metadata:
            raise ValueError(
                f"Composite type '{composite_type_name}' not found in '{schema_name}' schema. "
                f"Expected by function '{schema_name}.{composite_type_name}'."
            )

        # Step 2: Build annotations AND field descriptors
        annotations = {}
        gql_fields = {}  # NEW: Store field metadata

        for attr in composite_metadata.attributes:
            # Step 2a: Parse field metadata from comment (SpecQL puts metadata here)
            field_metadata = None
            if attr.comment:
                field_metadata = self.metadata_parser.parse_field_annotation(attr.comment)

            # Step 2b: Determine field name
            # Use metadata name (camelCase) if available, otherwise use attribute name
            field_name = field_metadata.name if field_metadata else attr.name

            # Step 2c: Map PostgreSQL type to Python type
            # Check if field is required (from SpecQL metadata)
            nullable = not field_metadata.required if field_metadata else True

            python_type = self.type_mapper.pg_type_to_python(attr.pg_type, nullable=nullable)

            # Step 2d: Create field descriptor with description
            from fraiseql.fields import FraiseQLField

            field_descriptor = FraiseQLField(
                field_type=python_type,
                description=attr.comment,  # PostgreSQL comment (NEW)
                purpose="input",
            )

            gql_fields[field_name] = field_descriptor
            annotations[field_name] = python_type

        # Step 3: Generate class name from composite type name
        # "type_create_contact_input" → "CreateContactInput"
        class_name = self._composite_type_to_class_name(composite_type_name)

        # Step 4: Create input class with field metadata
        input_cls = type(
            class_name,
            (object,),
            {
                "__annotations__": annotations,
                # Field descriptors as class attributes, like name: str = fraise_field(...)
                **gql_fields,
                "__doc__": composite_metadata.comment
                or f"Auto-generated from {composite_type_name}",
            },
        )

        return self._as_input_type(input_cls)

    def _composite_type_to_class_name(self, composite_type_name: str) -> str:
        """Convert composite type name to GraphQL input class name.

        SpecQL naming convention:
            type_create_contact_input → CreateContactInput

        Example:
            "type_create_contact_input" → "CreateContactInput"
        """
        # Remove "type_" prefix
        name = composite_type_name.replace("type_", "")

        # Remove "_input" suffix (we'll add it back as "Input")
        name = name.replace("_input", "")

        # Split by underscore and capitalize
        parts = name.split("_")
        class_name = "".join(part.capitalize() for part in parts)

        # Add "Input" suffix
        return f"{class_name}Input"

    async def generate_input_type(
        self,
        function_metadata: FunctionMetadata,
        annotation: MutationAnnotation,
        introspector: "PostgresIntrospector",
        context_params: Optional[dict[str, str]] = None,  # NEW: Explicit exclusion list
    ) -> Type:
        """Generate input class for mutation.

        Strategy:
        1. Look for JSONB parameter (SpecQL pattern: input_payload)
        2. If found, extract composite type name and introspect it (READ from DB)
        3. Otherwise, fall back to parameter-based generation (legacy)

        Args:
            function_metadata: Metadata from function introspection
            annotation: Parsed @fraiseql:mutation annotation
            introspector: PostgresIntrospector for composite type discovery
            context_params: Optional dict of context parameters to exclude from input

        Returns:
            Dynamically created input class

        Example (SpecQL pattern):
            Function (created by SpecQL):
                app.create_contact(input_tenant_id UUID, input_user_id UUID, input_payload JSONB)

            Generates from composite type (reads from DB):
                class CreateContactInput:
                    email: str
                    companyId: UUID | None
                    status: str

        Example (Legacy pattern):
            Function:
                fn_create_user(p_name TEXT, p_email TEXT)

            Generates from parameters:
                class CreateUserInput:
                    name: str
                    email: str
        """
        # STRATEGY 1: Try composite type-based generation (SpecQL pattern)
        jsonb_param = self._find_jsonb_input_parameter(function_metadata)

        if jsonb_param:
            # Found JSONB parameter → SpecQL pattern detected
            composite_type_name = self._extract_composite_type_name(function_metadata, annotation)

            if composite_type_name:
                try:
                    return await self._generate_from_composite_type(
                        composite_type_name, function_metadata.schema_name, introspector
                    )
                except ValueError as e:
                    # Composite type not found, fall back to parameter-based
                    logger.warning(
                        f"Composite type generation failed for "
                        f"{function_metadata.function_name}: {e}. "
                        f"Falling back to parameter-based generation."
                    )

        # STRATEGY 2: Fall back to parameter-based generation (legacy)
        return self._generate_from_parameters(function_metadata, annotation, context_params)

    def _generate_from_parameters(
        self,
        function_metadata: FunctionMetadata,
        annotation: MutationAnnotation,
        context_params: Optional[dict[str, str]] = None,
    ) -> Type:
        """Generate input class from function parameters (legacy pattern).

        This is the original implementation for backward compatibility.
        """
        class_name = self._function_to_input_name(function_metadata.function_name)

        annotations = {}

        # Get set of parameter names to exclude
        exclude_params = set(context_params.values()) if context_params else set()

        for param in function_metadata.parameters:
            # Skip if in explicit context_params list
            if param.name in exclude_params:
                continue

            # Skip authentication context parameters by prefix
            if param.name.startswith("auth_"):
                continue

            # Skip input_payload (composite type pattern)
            if param.name == "input_payload":
                continue

            # Skip output parameters
            if param.mode != "IN":
                continue

            # Map parameter to input field
            field_name = param.name.replace("p_", "")  # Remove p_ prefix
            python_type = self.type_mapper.pg_type_to_python(
                param.pg_type, nullable=(param.default_value is not None)
            )
            annotations[field_name] = python_type

        # Create input class
        input_cls = type(class_name, (object,), {"__annotations__": annotations})

        return self._as_input_type(input_cls)

    def _as_input_type(self, input_cls: Type) -> Type:
        """Make a generated class a FraiseQL input type, as ``@fraiseql.input`` does."""
        # Import here to avoid circular imports
        from fraiseql import input as fraiseql_input

        return fraiseql_input(input_cls)

    def _function_to_input_name(self, function_name: str) -> str:
        """Convert fn_create_user → CreateUserInput."""
        name = function_name.replace("fn_", "").replace("tv_", "")
        parts = name.split("_")
        # Capitalize each part and add "Input" suffix
        class_name = "".join(part.capitalize() for part in parts) + "Input"
        return class_name

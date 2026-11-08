"""Metadata parser for @fraiseql annotations in PostgreSQL comments.

This module parses YAML-formatted metadata from database object comments
to extract FraiseQL configuration for auto-discovery.
"""

from dataclasses import dataclass
from typing import Optional

import yaml


@dataclass
class TypeAnnotation:
    """Parsed @fraiseql:type annotation."""

    trinity: bool = False
    use_projection: bool = False
    description: Optional[str] = None
    expose_fields: Optional[list[str]] = None
    filter_config: Optional[dict] = None


@dataclass
@dataclass
class MutationAnnotation:
    """Parsed @fraiseql:mutation annotation."""

    name: str
    success_type: str
    error_type: str
    description: Optional[str] = None
    input_type: Optional[str] = None
    context_params: Optional[list[str]] = None  # NEW: Explicit context params
    result_name: Optional[str] = None  # GraphQL name of the result union


@dataclass
class FieldMetadata:
    """Parsed @fraiseql:field annotation from composite type column comment.

    SpecQL puts this metadata in column comments. We parse it to understand
    field requirements (required, type, etc.).

    Example comment:
        @fraiseql:field name=email,type=String!,required=true

    Parses to:
        FieldMetadata(name="email", graphql_type="String!", required=True, ...)
    """

    name: str  # GraphQL field name (camelCase)
    graphql_type: str  # GraphQL type (e.g., "String!", "UUID")
    required: bool  # Is field required (non-null)?
    is_enum: bool = False  # Is this an enum type?
    description: Optional[str] = None


class MetadataParser:
    """Parse @fraiseql annotations from PostgreSQL comments."""

    ANNOTATION_MARKER = "@fraiseql:"

    def parse_type_annotation(self, comment: Optional[str]) -> Optional[TypeAnnotation]:
        """Parse @fraiseql:type annotation from view comment.

        Format:
            @fraiseql:type
            trinity: true
            description: User account
            expose_fields:
              - id
              - name
              - email

        Returns:
            TypeAnnotation if valid, None otherwise
        """
        if not comment or self.ANNOTATION_MARKER not in comment:
            return None

        try:
            # Extract YAML content after marker
            marker = "@fraiseql:type"
            if marker not in comment:
                return None

            yaml_start = comment.index(marker) + len(marker)
            yaml_content = comment[yaml_start:].strip()

            # Handle multi-line YAML
            # Stop at next @fraiseql: marker or end of comment
            if self.ANNOTATION_MARKER in yaml_content:
                next_marker = yaml_content.index(self.ANNOTATION_MARKER)
                yaml_content = yaml_content[:next_marker]

            # Parse YAML
            data = yaml.safe_load(yaml_content) or {}

            return TypeAnnotation(
                trinity=data.get("trinity", False),
                use_projection=data.get("use_projection", False),
                description=data.get("description"),
                expose_fields=data.get("expose_fields"),
                filter_config=data.get("filters"),
            )

        except (yaml.YAMLError, ValueError) as e:
            # Log warning but don't fail
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to parse @fraiseql:type: {e}")
            return None

    def parse_mutation_annotation(self, comment: Optional[str]) -> Optional[MutationAnnotation]:
        """Parse @fraiseql:mutation annotation from function comment.

        Now supports context_params:
            @fraiseql:mutation
            name: createContact
            success_type: Contact
            error_type: ContactError
            context_params: [auth_tenant_id, auth_user_id]  # NEW
            result_name: CreateContactResult  # optional: the result union's name
        """
        if not comment or "@fraiseql:mutation" not in comment:
            return None

        # Extract YAML content
        lines = comment.split("\n")
        yaml_lines = []
        in_annotation = False

        for line in lines:
            if "@fraiseql:mutation" in line:
                in_annotation = True
                continue
            if in_annotation:
                if line.strip() and not line.strip().startswith("@"):
                    yaml_lines.append(line)
                elif line.strip().startswith("@"):
                    break

        if not yaml_lines:
            return None

        # Parse YAML
        try:
            import yaml

            data = yaml.safe_load("\n".join(yaml_lines))

            # Required fields
            name = data.get("name")
            success_type = data.get("success_type")
            error_type = data.get("error_type")

            if not all([name, success_type, error_type]):
                return None

            # Optional fields
            description = data.get("description")
            input_type = data.get("input_type")
            context_params = data.get("context_params")  # NEW: Parse context_params array
            result_name = data.get("result_name")

            return MutationAnnotation(
                name=name,
                description=description,
                success_type=success_type,
                error_type=error_type,
                input_type=input_type,
                context_params=context_params,  # NEW
                result_name=result_name,
            )
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to parse mutation annotation: {e}")
            return None

    def parse_field_annotation(self, comment: str | None) -> FieldMetadata | None:
        """Parse @fraiseql:field annotation from composite type column comment.

        SpecQL puts this metadata in column comments when generating composite types.
        We read and parse it.

        Format (created by SpecQL):
            @fraiseql:field name=email,type=String!,required=true

        Args:
            comment: Column comment string (from pg_attribute)

        Returns:
            FieldMetadata if annotation found, None otherwise

        Example:
            >>> parser = MetadataParser()
            >>> # This comment was created by SpecQL
            >>> comment = "@fraiseql:field name=email,type=String!,required=true"
            >>> metadata = parser.parse_field_annotation(comment)
            >>> metadata.name
            'email'
            >>> metadata.required
            True
        """
        if not comment or "@fraiseql:field" not in comment:
            return None

        # Extract key-value pairs from annotation
        # Format: @fraiseql:field name=email,type=String!,required=true

        # Find the @fraiseql:field line
        lines = comment.split("\n")
        field_line = next((line for line in lines if "@fraiseql:field" in line), None)

        if not field_line:
            return None

        # Remove '@fraiseql:field' prefix
        content = field_line.split("@fraiseql:field", 1)[1].strip()

        # Parse key=value pairs
        params = {}
        current_key = None
        current_value = []

        # Split by comma, but handle values that might contain commas
        parts = content.split(",")

        for part in parts:
            if "=" in part and not current_key:
                # New key=value pair
                key, value = part.split("=", 1)
                current_key = key.strip()
                current_value = [value.strip()]
            elif "=" in part and current_key:
                # Save previous key-value, start new one
                params[current_key] = ",".join(current_value)
                key, value = part.split("=", 1)
                current_key = key.strip()
                current_value = [value.strip()]
            else:
                # Continuation of previous value
                current_value.append(part.strip())

        # Save last key-value
        if current_key:
            params[current_key] = ",".join(current_value)

        # Build FieldMetadata from parsed params
        name = params.get("name", "")
        graphql_type = params.get("type", "String")
        required = params.get("required", "false").lower() == "true"
        is_enum = params.get("enum", "false").lower() == "true"
        description = params.get("description")

        return FieldMetadata(
            name=name,
            graphql_type=graphql_type,
            required=required,
            is_enum=is_enum,
            description=description,
        )

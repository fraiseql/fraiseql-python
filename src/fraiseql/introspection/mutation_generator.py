"""Mutation generation for AutoFraiseQL.

This module provides utilities to generate GraphQL mutations from PostgreSQL
functions with automatic Union return type handling.
"""

import logging
from typing import TYPE_CHECKING, Callable, Type

from .input_generator import InputGenerator
from .metadata_parser import MutationAnnotation
from .postgres_introspector import FunctionMetadata

if TYPE_CHECKING:
    from .postgres_introspector import PostgresIntrospector

logger = logging.getLogger(__name__)


class MutationGenerator:
    """Generate mutations from PostgreSQL functions."""

    def __init__(self, input_generator: InputGenerator):
        self.input_generator = input_generator

    def _extract_context_params(
        self, function_metadata: FunctionMetadata, annotation: MutationAnnotation
    ) -> dict[str, str]:
        """Extract context parameters from function signature.

        NEW STANDARD (Phase 5.6):
            auth_tenant_id UUID   → context["tenant_id"]
            auth_user_id UUID     → context["user_id"]

        Priority:
        1. Explicit metadata (annotation.context_params)
        2. Auto-detection by auth_ prefix

        BREAKING CHANGE: No longer supports input_* or input_pk_* conventions.
        Use auth_* prefix for authentication context parameters.

        Args:
            function_metadata: Function metadata from introspection
            annotation: Parsed mutation annotation (may contain explicit context_params)

        Returns:
            Mapping of context_key → function_parameter_name

        Example:
            Function signature:
                app.qualify_lead(p_contact_id UUID, auth_tenant_id UUID, auth_user_id UUID)

        Returns:
                {
                    "tenant_id": "auth_tenant_id",
                    "user_id": "auth_user_id"
                }
        """
        context_params = {}

        # PRIORITY 1: Explicit metadata (SpecQL provides this)
        if annotation and annotation.context_params:
            for param_name in annotation.context_params:
                # Find the parameter in function metadata
                param = next(
                    (p for p in function_metadata.parameters if p.name == param_name), None
                )
                if param:
                    # Extract context key from parameter name
                    # auth_tenant_id → tenant_id
                    # auth_user_id → user_id
                    if param_name.startswith("auth_"):
                        context_key = param_name.replace("auth_", "")
                    else:
                        # Non-standard naming, use as-is
                        context_key = param_name

                    context_params[context_key] = param_name

            return context_params

        # PRIORITY 2: Auto-detection by auth_ prefix
        for param in function_metadata.parameters:
            # Standard: auth_tenant_id → tenant_id
            if param.name == "auth_tenant_id":
                context_params["tenant_id"] = param.name

            # Standard: auth_user_id → user_id
            elif param.name == "auth_user_id":
                context_params["user_id"] = param.name

            # Generic: auth_<name> → <name>
            elif param.name.startswith("auth_"):
                context_key = param.name.replace("auth_", "")
                context_params[context_key] = param.name

        return context_params

    async def generate_mutation_for_function(
        self,
        function_metadata: FunctionMetadata,
        annotation: MutationAnnotation,
        type_registry: dict[str, Type],
        introspector: "PostgresIntrospector",
    ) -> Callable | None:
        """Generate mutation from function (created by SpecQL).

        This method READS function metadata and generates Python code.
        It does NOT create or modify the database.

        Steps:
        1. Generate input type (from composite type that SpecQL created)
        2. Resolve success/error types
        3. Extract context parameters (READ from function signature)
        4. Create mutation function
        5. Apply @fraiseql.mutation decorator

        Args:
            function_metadata: Metadata from function introspection (READ from DB)
            annotation: Parsed @fraiseql:mutation annotation
            type_registry: Registry of available types
            introspector: PostgresIntrospector for composite type discovery (NEW)

        Returns:
            Decorated mutation function or None if generation fails
        """
        # 1. Extract context parameters (for exclusion from input schema)
        context_params = self._extract_context_params(function_metadata, annotation)

        # 2. Generate input type (READS composite type from DB, excluding context params)
        input_cls = await self.input_generator.generate_input_type(
            function_metadata,
            annotation,
            introspector,  # PASS INTROSPECTOR
            context_params,  # Pass for exclusion
        )

        # 3. Get success/error types
        success_type = type_registry.get(annotation.success_type)
        error_type = type_registry.get(annotation.error_type)

        if not success_type or not error_type:
            logger.warning(
                f"Cannot generate mutation {function_metadata.function_name}: "
                f"missing types {annotation.success_type} or {annotation.error_type}"
            )
            return None

        # 4. Create mutation class dynamically
        mutation_class = self._create_mutation_class(
            function_metadata, annotation, input_cls, success_type, error_type
        )

        # 5. Apply @mutation decorator with context params
        from fraiseql import mutation

        decorated_mutation = mutation(
            mutation_class,
            function=function_metadata.function_name,
            schema=function_metadata.schema_name,
            context_params=context_params,  # ADD THIS
        )
        # The comment's name: is the field name from fraiseql 2.0.0. Until then the
        # field keeps the name taken from the function, with a FutureWarning.
        decorated_mutation.__fraiseql_mutation__.default_graphql_name = annotation.name
        decorated_mutation.__fraiseql_mutation__.result_name = annotation.result_name

        return decorated_mutation

    def _create_mutation_class(
        self,
        function_metadata: FunctionMetadata,
        annotation: MutationAnnotation,
        input_cls: Type,
        success_type: Type,
        error_type: Type,
    ) -> Type:
        """Create a mutation class with proper type annotations."""
        # Create class name
        class_name = self._function_to_mutation_class_name(function_metadata.function_name)

        # Create class with type annotations
        mutation_cls = type(
            class_name,
            (object,),
            {
                "__annotations__": {
                    "input": input_cls,
                    "success": success_type,
                    "error": error_type,
                },
                "__doc__": (
                    annotation.description  # Priority 1: Explicit annotation
                    or function_metadata.comment  # Priority 2: PostgreSQL comment (NEW)
                    # Priority 3: Fallback
                    or f"Auto-generated mutation from {function_metadata.function_name}"
                ),
                "__module__": "fraiseql.introspection.generated",
            },
        )

        return mutation_cls

    def _function_to_mutation_class_name(self, function_name: str) -> str:
        """Convert fn_create_user → CreateUser."""
        name = function_name.replace("fn_", "").replace("tv_", "")
        parts = name.split("_")
        # Capitalize each part
        return "".join(part.capitalize() for part in parts)

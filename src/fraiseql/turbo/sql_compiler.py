"""SQL template compiler for TurboRouter."""

import ast
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Optional

from graphql import (
    DocumentNode,
    FieldNode,
    FragmentDefinitionNode,
    InlineFragmentNode,
    OperationDefinitionNode,
    SelectionSetNode,
)

from fraiseql.utils.casing import to_snake_case


@dataclass
class SQLCompilationResult:
    """Result of SQL compilation."""

    sql_template: str
    param_mapping: dict[str, str]
    used_views: set[str]
    required_fields: set[str]


@dataclass
class ResolverSQLInfo:
    """SQL information extracted from resolver."""

    sql_template: str
    param_mapping: dict[str, str]
    view_name: str
    is_find_one: bool


class SQLCompiler:
    """Compiles GraphQL queries into optimized SQL templates."""

    def compile_from_graphql(
        self, document: DocumentNode, view_mapping: dict[str, str]
    ) -> SQLCompilationResult:
        """Generate SQL template from GraphQL AST.

        Args:
            document: Parsed GraphQL document
            view_mapping: Mapping of GraphQL types to database views

        Returns:
            SQLCompilationResult with SQL template and metadata
        """
        # Extract operation and fragments
        operation = None
        fragments = {}

        for definition in document.definitions:
            if isinstance(definition, OperationDefinitionNode):
                operation = definition
            elif isinstance(definition, FragmentDefinitionNode):
                fragments[definition.name.value] = definition

        if not operation:
            raise ValueError("No operation found in document")

        # Analyze the query structure
        analyzer = QueryStructureAnalyzer(fragments, view_mapping)
        structure = analyzer.analyze(operation)

        # Generate SQL based on structure
        sql_generator = SQLTemplateGenerator(view_mapping)
        sql_template = sql_generator.generate(structure)

        # Extract parameter mapping
        param_mapping = self._extract_param_mapping(operation)

        return SQLCompilationResult(
            sql_template=sql_template,
            param_mapping=param_mapping,
            used_views=structure.used_views,
            required_fields=structure.required_fields,
        )

    def extract_from_resolver(self, resolver_func: Callable) -> Optional[ResolverSQLInfo]:
        """Extract SQL pattern from resolver function.

        Args:
            resolver_func: Resolver function to analyze

        Returns:
            ResolverSQLInfo if extraction successful, None otherwise
        """
        try:
            # Get function source
            source = inspect.getsource(resolver_func)

            # Parse AST
            tree = ast.parse(source)

            # Find database calls
            analyzer = ResolverAnalyzer()
            analyzer.visit(tree)

            if not analyzer.db_calls:
                return None

            # Extract the main database call
            main_call = analyzer.db_calls[0]

            # Build SQL template
            sql_template = self._build_sql_template_from_call(main_call)

            # Extract parameter mapping
            param_mapping = self._extract_params_from_call(main_call)

            return ResolverSQLInfo(
                sql_template=sql_template,
                param_mapping=param_mapping,
                view_name=main_call.view_name,
                is_find_one=main_call.is_find_one,
            )

        except Exception:
            return None

    def _extract_param_mapping(self, operation: OperationDefinitionNode) -> dict[str, str]:
        """Extract parameter mapping from operation."""
        param_mapping = {}

        # Extract variable definitions
        if operation.variable_definitions:
            for var_def in operation.variable_definitions:
                var_name = var_def.variable.name.value
                # Map to SQL parameter name (PostgreSQL style)
                param_mapping[var_name] = f"%({var_name})s"

        # Extract inline arguments
        # This would need to traverse the selection set
        # and find all argument usages

        return param_mapping

    def _build_sql_template_from_call(self, db_call: "DBCall") -> str:
        """Build SQL template from database call info."""
        if db_call.is_find_one:
            # Single object query
            return f"""
            SELECT to_json(t.*) as result
            FROM {db_call.view_name} t
            WHERE {{where_clause}}
            LIMIT 1
            """
        # List query
        return f"""
            SELECT json_agg(t.*) as result
            FROM {db_call.view_name} t
            WHERE {{where_clause}}
            {{order_clause}}
            {{limit_clause}}
            """

    def _extract_params_from_call(self, db_call: "DBCall") -> dict[str, str]:
        """Extract parameters from database call."""
        # This is simplified - would need proper AST analysis
        params = {}
        for key in db_call.filters:
            params[key] = f"%({key})s"
        return params


@dataclass
class QueryStructure:
    """Analyzed query structure."""

    root_field: str
    selections: list[str]
    filters: dict[str, Any]
    used_views: set[str]
    required_fields: set[str]
    has_pagination: bool
    has_ordering: bool
    max_depth: int


class QueryStructureAnalyzer:
    """Analyzes GraphQL query structure."""

    def __init__(
        self, fragments: dict[str, FragmentDefinitionNode], view_mapping: dict[str, str]
    ) -> None:
        self.fragments = fragments
        self.view_mapping = view_mapping
        self.used_views = set()
        self.required_fields = set()

    def analyze(self, operation: OperationDefinitionNode) -> QueryStructure:
        """Analyze operation structure."""
        # Get root field
        root_selection = operation.selection_set.selections[0]
        if not isinstance(root_selection, FieldNode):
            raise TypeError("Expected field selection at root")

        root_field = root_selection.name.value

        # Analyze selections
        selections = self._extract_selections(root_selection.selection_set)

        # Extract filters from arguments
        filters = self._extract_filters(root_selection.arguments)

        # Check for pagination and ordering
        has_pagination = any(
            arg.name.value in ["limit", "offset"] for arg in root_selection.arguments
        )
        has_ordering = any(arg.name.value == "orderBy" for arg in root_selection.arguments)

        # Calculate depth
        max_depth = self._calculate_depth(root_selection.selection_set)

        return QueryStructure(
            root_field=root_field,
            selections=selections,
            filters=filters,
            used_views=self.used_views,
            required_fields=self.required_fields,
            has_pagination=has_pagination,
            has_ordering=has_ordering,
            max_depth=max_depth,
        )

    def _extract_selections(
        self, selection_set: Optional[SelectionSetNode], path: str = ""
    ) -> list[str]:
        """Extract all field selections."""
        if not selection_set:
            return []

        selections = []

        for selection in selection_set.selections:
            if isinstance(selection, FieldNode):
                field_name = selection.name.value
                field_path = f"{path}.{field_name}" if path else field_name
                selections.append(field_path)

                # Track required fields
                self.required_fields.add(field_name)

                # Recurse into sub-selections
                if selection.selection_set:
                    sub_selections = self._extract_selections(selection.selection_set, field_path)
                    selections.extend(sub_selections)

            elif isinstance(selection, InlineFragmentNode):
                # Handle inline fragments
                sub_selections = self._extract_selections(selection.selection_set, path)
                selections.extend(sub_selections)

            elif hasattr(selection, "name"):  # Fragment spread
                # Resolve fragment
                fragment_name = selection.name.value
                if fragment_name in self.fragments:
                    fragment = self.fragments[fragment_name]
                    sub_selections = self._extract_selections(fragment.selection_set, path)
                    selections.extend(sub_selections)

        return selections

    def _extract_filters(self, arguments: list) -> dict[str, Any]:
        """Extract filter arguments."""
        filters = {}

        for arg in arguments:
            arg_name = arg.name.value
            # Convert argument value to filter
            # This is simplified - would need proper value extraction
            filters[arg_name] = f"${arg_name}"

        return filters

    def _calculate_depth(
        self, selection_set: Optional[SelectionSetNode], current_depth: int = 0
    ) -> int:
        """Calculate maximum query depth."""
        if not selection_set:
            return current_depth

        max_depth = current_depth

        for selection in selection_set.selections:
            if isinstance(selection, FieldNode) and selection.selection_set:
                depth = self._calculate_depth(selection.selection_set, current_depth + 1)
                max_depth = max(max_depth, depth)

        return max_depth


class SQLTemplateGenerator:
    """Generates SQL templates from query structure."""

    def __init__(self, view_mapping: dict[str, str]) -> None:
        self.view_mapping = view_mapping

    def generate(self, structure: QueryStructure) -> str:
        """Generate SQL template from query structure."""
        # Determine the view name
        view_name = self.view_mapping.get(structure.root_field, f"{structure.root_field}_view")

        # Build field selection
        field_selection = self._build_field_selection(structure.selections)

        # Build WHERE clause
        where_clause = self._build_where_clause(structure.filters)

        # Build complete SQL
        sql_parts = [
            "SELECT",
            field_selection,
            f"FROM {view_name}",
        ]

        if where_clause:
            sql_parts.append(f"WHERE {where_clause}")

        if structure.has_ordering:
            sql_parts.append("ORDER BY %(orderBy)s")

        if structure.has_pagination:
            sql_parts.append("LIMIT %(limit)s OFFSET %(offset)s")

        return "\n".join(sql_parts)

    def _build_field_selection(self, selections: list[str]) -> str:
        """Build JSONB field selection."""
        # Group selections by depth
        root_fields = []
        nested_fields = {}

        for selection in selections:
            parts = selection.split(".")
            if len(parts) == 1:
                root_fields.append(parts[0])
            else:
                root = parts[0]
                if root not in nested_fields:
                    nested_fields[root] = []
                nested_fields[root].append(".".join(parts[1:]))

        # Build JSONB object
        json_parts = []

        for field in root_fields:
            if field in nested_fields:
                # Field with nested selections
                nested_json = self._build_nested_json(field, nested_fields[field])
                json_parts.append(f"'{field}', {nested_json}")
            else:
                # Simple field
                snake_field = to_snake_case(field)
                json_parts.append(f"'{field}', {snake_field}")

        return f"jsonb_build_object({', '.join(json_parts)})::text as result"

    def _build_nested_json(self, field: str, nested_selections: list[str]) -> str:
        """Build nested JSONB selection."""
        # This is simplified - would need recursive building
        snake_field = to_snake_case(field)
        return f"jsonb_build_object('id', {snake_field}->>'id')"

    def _build_where_clause(self, filters: dict[str, str]) -> str:
        """Build WHERE clause from filters."""
        conditions = []

        for field, param in filters.items():
            snake_field = to_snake_case(field)
            conditions.append(f"{snake_field} = {param}")

        return " AND ".join(conditions) if conditions else "1=1"


@dataclass
class DBCall:
    """Represents a database call in resolver."""

    view_name: str
    is_find_one: bool
    filters: dict[str, Any]
    selections: list[str]


class ResolverAnalyzer(ast.NodeVisitor):
    """Analyzes resolver AST to find database calls."""

    def __init__(self) -> None:
        self.db_calls = []

    def visit_Call(self, node: ast.Call) -> None:
        """Visit function calls to find db operations."""
        # Check if it's a db.find or db.find_one call
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "db"
        ):
            method_name = node.func.attr
            if method_name in ["find", "find_one"]:
                db_call = self._extract_db_call(node, method_name == "find_one")
                if db_call:
                    self.db_calls.append(db_call)

        self.generic_visit(node)

    def _extract_db_call(self, node: ast.Call, is_find_one: bool) -> Optional[DBCall]:
        """Extract database call information."""
        if not node.args:
            return None

        # First argument should be view name
        if isinstance(node.args[0], ast.Constant):
            view_name = node.args[0].value
        else:
            return None

        # Second argument might be filters
        filters = {}
        if len(node.args) > 1:
            # Try to extract filter dict
            # This is simplified - would need proper AST analysis
            pass

        return DBCall(view_name=view_name, is_find_one=is_find_one, filters=filters, selections=[])

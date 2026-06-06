"""GraphQL HTTP entrypoint router for GraphNote, built on Starlette."""

import json
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from graphql import GraphQLSchema
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route, Router

from fraiseql.core.rust_pipeline import RustResponseBytes
from fraiseql.fastapi.json_encoder import FraiseQLJSONResponse, clean_unset_values
from fraiseql.gql.schema_builder import SchemaRegistry
from fraiseql.graphql.execute import execute_graphql

if TYPE_CHECKING:
    from fraiseql.security.authorization import Authorizer


class GraphNoteRouter(Router):
    """Starlette router handling GraphQL requests via /graphql endpoint."""

    def __init__(
        self,
        schema: GraphQLSchema,
        context_getter: Callable[[Request], Any] | None = None,
    ) -> None:
        """Initialize the GraphNoteRouter.

        Args:
            schema: The GraphQL schema to execute queries against.
            context_getter: Optional callable taking a Starlette Request and returning
                a context object passed to resolvers. Defaults to empty dict.
        """
        self.schema = schema
        self.context_getter = context_getter or (lambda _: {})

        routes = [
            Route("/graphql", self.handle_graphql, methods=["GET", "POST"]),
        ]
        super().__init__(routes=routes)

    async def handle_graphql(self, request: Request) -> FraiseQLJSONResponse:
        """Handle incoming HTTP request with GraphQL query.

        Supports GET (query params) and POST (JSON body).

        Args:
            request: The incoming Starlette Request.

        Returns:
            JSONResponse containing GraphQL execution result.
        """
        if request.method == "GET":
            query = request.query_params.get("query", "")
            variables_raw = request.query_params.get("variables")
            variables: dict[str, Any] | None = None
            if variables_raw:
                try:
                    variables = json.loads(variables_raw)
                except json.JSONDecodeError:
                    return FraiseQLJSONResponse(
                        {"errors": [{"message": "Invalid JSON in variables parameter"}]},
                        status_code=400,
                    )
            operation_name = request.query_params.get("operationName")
        else:
            try:
                data = await request.json()
            except json.JSONDecodeError:
                return FraiseQLJSONResponse(
                    {"errors": [{"message": "Invalid JSON"}]},
                    status_code=400,
                )
            query = data.get("query")
            variables = data.get("variables")
            operation_name = data.get("operationName")

        context_value = self.context_getter(request)

        # Use execute_graphql() instead of graphql() to support RustResponseBytes pass-through
        result = await execute_graphql(
            self.schema,
            query,
            variable_values=variables,
            operation_name=operation_name,
            context_value=context_value,
        )

        # 🚀 RUST RESPONSE BYTES PASS-THROUGH:
        # Check if execute_graphql() returned RustResponseBytes (zero-copy path)
        # If so, return bytes directly without any Python serialization
        if isinstance(result, RustResponseBytes):
            return Response(
                content=bytes(result),
                media_type="application/json",
                status_code=200,
            )

        # Normal ExecutionResult path (backwards compatible)
        response_data: dict[str, Any] = {}

        if result.errors:
            response_data["errors"] = [
                {
                    "message": e.message,
                    "extensions": clean_unset_values(e.extensions) if e.extensions else {},
                }
                for e in result.errors
            ]

        if result.data is not None:
            response_data["data"] = result.data

        status = 200 if not result.errors else 400
        return FraiseQLJSONResponse(response_data, status_code=status)


def build_fraiseql_schema(
    *,
    query_types: Sequence[type] = (),
    mutation_resolvers: Sequence[Callable[..., Any]] = (),
    authorizer: "Authorizer | None" = None,
) -> GraphQLSchema:
    """Compose a GraphQL schema from provided query types and mutation resolvers.

    Args:
        query_types: Iterable of Python dataclasses decorated as GraphNote types.
        mutation_resolvers: Iterable of async resolver callables for mutations.
        authorizer: Optional global default operation authorizer (issue #362),
            installed as ``SchemaRegistry.default_authorizer``. ``None`` leaves the
            slot cleared (behavior unchanged).

    Returns:
        GraphQLSchema object with query and mutation types built.
    """
    registry = SchemaRegistry.get_instance()
    registry.set_default_authorizer(authorizer)

    for typ in query_types:
        registry.register_type(typ)

    for fn in mutation_resolvers:
        registry.register_mutation(fn)

    query_type = registry.build_query_type()
    mutation_type = registry.build_mutation_type()

    return GraphQLSchema(
        query=query_type,
        mutation=mutation_type,
    )

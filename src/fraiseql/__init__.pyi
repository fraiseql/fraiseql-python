from typing import Any, Callable, Type, TypeVar, dataclass_transform, overload

from .mutations.error_config import MutationErrorConfig as MutationErrorConfig

_T = TypeVar("_T")
_F = TypeVar("_F", bound=Callable[..., Any])

# Helper function for fields (declared first: referenced by the
# ``@dataclass_transform`` field specifiers on the type decorators below).
def fraise_field(
    *,
    description: str | None = None,
    alias: str | None = None,
    deprecation_reason: str | None = None,
    default: Any = ...,
) -> Any: ...

# Core type decorators
@dataclass_transform(kw_only_default=True, field_specifiers=(fraise_field,))
@overload
def fraise_type_decorator(cls: Type[_T]) -> Type[_T]: ...
@overload
def fraise_type_decorator(
    *,
    sql_source: str | None = None,
    jsonb_column: str | None = None,
    implements: list[Type[Any]] | None = None,
    resolve_nested: bool = False,
    authorize_fields: list[str] | None = None,
) -> Callable[[Type[_T]], Type[_T]]: ...
def fraise_type_decorator(
    cls: Type[_T] | None = None,
    *,
    sql_source: str | None = None,
    jsonb_column: str | None = None,
    implements: list[Type[Any]] | None = None,
    resolve_nested: bool = False,
    authorize_fields: list[str] | None = None,
) -> Type[_T] | Callable[[Type[_T]], Type[_T]]: ...
@dataclass_transform(kw_only_default=True, field_specifiers=(fraise_field,))
@overload
def fraise_input_decorator(cls: Type[_T]) -> Type[_T]: ...
@overload
def fraise_input_decorator(
    *,
    description: str | None = None,
) -> Callable[[Type[_T]], Type[_T]]: ...
def fraise_input_decorator(
    cls: Type[_T] | None = None,
    *,
    description: str | None = None,
) -> Type[_T] | Callable[[Type[_T]], Type[_T]]: ...
@dataclass_transform(kw_only_default=True, field_specifiers=(fraise_field,))
def success(cls: Type[_T]) -> Type[_T]: ...
@dataclass_transform(kw_only_default=True, field_specifiers=(fraise_field,))
def error(cls: Type[_T]) -> Type[_T]: ...
def result(cls: Type[_T]) -> Type[_T]: ...
def enum(cls: Type[_T]) -> Type[_T]: ...
@dataclass_transform(kw_only_default=True, field_specifiers=(fraise_field,))
def interface(cls: Type[_T]) -> Type[_T]: ...

# Query decorator
@overload
def query(func: _F) -> _F: ...
@overload
def query() -> Callable[[_F], _F]: ...
def query(func: _F | None = None) -> _F | Callable[[_F], _F]: ...

# Field decorator
@overload
def field(func: _F) -> _F: ...
@overload
def field(
    *,
    description: str | None = None,
    deprecation_reason: str | None = None,
) -> Callable[[_F], _F]: ...
def field(
    func: _F | None = None,
    *,
    description: str | None = None,
    deprecation_reason: str | None = None,
) -> _F | Callable[[_F], _F]: ...

# Dataloader field decorator
@overload
def dataloader_field(func: _F) -> _F: ...
@overload
def dataloader_field(
    *,
    loader_key: str | None = None,
    description: str | None = None,
) -> Callable[[_F], _F]: ...
def dataloader_field(
    func: _F | None = None,
    *,
    loader_key: str | None = None,
    description: str | None = None,
) -> _F | Callable[[_F], _F]: ...

# Mutation decorator
@overload
def mutation(_cls: _T) -> _T: ...
@overload
def mutation(
    *,
    function: str | None = None,
    schema: str | None = None,
    context_params: dict[str, str] | None = None,
    error_config: MutationErrorConfig | None = None,
    enable_cascade: bool = False,
    authorizer: Any | None = None,
) -> Callable[[_T], _T]: ...
def mutation(
    _cls: _T | None = None,
    *,
    function: str | None = None,
    schema: str | None = None,
    context_params: dict[str, str] | None = None,
    error_config: MutationErrorConfig | None = None,
    enable_cascade: bool = False,
    authorizer: Any | None = None,
) -> _T | Callable[[_T], _T]: ...

# Subscription decorator
@overload
def subscription(func: _F) -> _F: ...
@overload
def subscription() -> Callable[[_F], _F]: ...
def subscription(func: _F | None = None) -> _F | Callable[[_F], _F]: ...

# Scalar field types
class Date:
    def __init__(self, value: str | None = None) -> None: ...

class DateTime:
    def __init__(self, value: str | None = None) -> None: ...

class JSON:
    def __init__(self, value: Any = None) -> None: ...

class EmailAddress:
    def __init__(self, value: str | None = None) -> None: ...

class IpAddress:
    def __init__(self, value: str | None = None) -> None: ...

class MacAddress:
    def __init__(self, value: str | None = None) -> None: ...

class Port:
    def __init__(self, value: int | None = None) -> None: ...

class Hostname:
    def __init__(self, value: str | None = None) -> None: ...

# Generic types
class Connection:
    edges: list[Any]
    page_info: Any
    total_count: int | None

class Edge:
    node: Any
    cursor: str

class PageInfo:
    has_next_page: bool
    has_previous_page: bool
    start_cursor: str | None
    end_cursor: str | None

def create_connection(
    items: list[Any],
    *,
    first: int | None = None,
    after: str | None = None,
    last: int | None = None,
    before: str | None = None,
) -> Connection: ...

# CQRS classes
class CQRSRepository:
    def __init__(self, connection_or_pool: Any) -> None: ...
    async def find(
        self,
        view: str,
        filters: dict[str, Any] | None = None,
        *,
        limit: int | None = None,
        offset: int | None = None,
        order_by: str | list[str] | None = None,
    ) -> list[dict[str, Any]]: ...
    async def find_one(
        self,
        view: str,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None: ...
    async def execute_function(
        self,
        function_name: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

class CQRSExecutor:
    def __init__(self, repository: CQRSRepository) -> None: ...

# Schema builder
def build_fraiseql_schema(
    types: list[Type[Any]] | None = None,
    mutations: list[Type[Any]] | None = None,
    queries: list[Type[Any]] | None = None,
    subscriptions: list[Type[Any]] | None = None,
) -> Any: ...

# Error configurations
ALWAYS_DATA_CONFIG: MutationErrorConfig
DEFAULT_ERROR_CONFIG: MutationErrorConfig
STRICT_STATUS_CONFIG: MutationErrorConfig

# Constants
UNSET: Any

# Auth types (when available)
class AuthProvider: ...

class UserContext:
    user_id: str
    roles: list[str]
    permissions: list[str]

def requires_auth(
    func: _F | None = None,
    *,
    optional: bool = False,
) -> _F | Callable[[_F], _F]: ...
def requires_role(
    role: str,
    *,
    optional: bool = False,
) -> Callable[[_F], _F]: ...
def requires_permission(
    permission: str,
    *,
    optional: bool = False,
) -> Callable[[_F], _F]: ...

class Auth0Config:
    domain: str
    audience: str
    algorithms: list[str]

class Auth0Provider(AuthProvider):
    def __init__(self, config: Auth0Config) -> None: ...

# FastAPI integration (FastAPI is a core dependency; typed here as the
# available API. At runtime these fall back to ``None`` if the import ever
# fails, but the stub describes the usable, installed surface.)
from .fastapi import FraiseQLConfig as FraiseQLConfig
from .fastapi import create_fraiseql_app as create_fraiseql_app

# Operation-level authorization (issue #362)
from .security.authorization import AuthorizationDecision as AuthorizationDecision
from .security.authorization import Authorizer as Authorizer
from .security.authorization import normalize_decision as normalize_decision

# Aliases for backwards compatibility
fraise_type = fraise_type_decorator
fraise_input = fraise_input_decorator
fraise_enum = enum
fraise_interface = interface

# Core aliases
type = fraise_type  # noqa: A001
input = fraise_input  # noqa: A001

__version__: str

__all__ = [
    "ALWAYS_DATA_CONFIG",
    "DEFAULT_ERROR_CONFIG",
    "JSON",
    "STRICT_STATUS_CONFIG",
    # Constants
    "UNSET",
    "Auth0Config",
    "Auth0Provider",
    # Auth (optional)
    "AuthProvider",
    # Operation authorization (issue #362)
    "AuthorizationDecision",
    "Authorizer",
    "CQRSExecutor",
    # CQRS
    "CQRSRepository",
    # Generic types
    "Connection",
    # Scalar types
    "Date",
    "DateTime",
    "Edge",
    "EmailAddress",
    # FastAPI integration (optional)
    "FraiseQLConfig",
    "Hostname",
    "IpAddress",
    "MacAddress",
    # Error configs
    "MutationErrorConfig",
    "PageInfo",
    "Port",
    "UserContext",
    # Schema
    "build_fraiseql_schema",
    "create_connection",
    # FastAPI integration (optional)
    "create_fraiseql_app",
    "dataloader_field",
    "enum",
    "error",
    "field",
    "fraise_enum",
    "fraise_field",
    "fraise_input",
    "fraise_input_decorator",
    "fraise_interface",
    # Aliases
    "fraise_type",
    # Core decorators
    "fraise_type_decorator",
    "input",
    "interface",
    "mutation",
    "normalize_decision",
    "query",
    "requires_auth",
    "requires_permission",
    "requires_role",
    "result",
    "subscription",
    "success",
    "type",
]

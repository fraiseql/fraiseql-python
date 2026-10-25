# Type stub for the ``fraiseql`` package.
#
# It re-exports the runtime names from the modules that define them, so type checkers
# read each signature from the code itself. What it adds over ``__init__.py``:
# ``fraiseql.type`` and ``fraiseql.input`` (served by the module ``__getattr__`` so that
# ``from fraiseql import *`` doesn't shadow the builtins), the lazily loaded
# ``fraiseql_rs`` extension, and the FastAPI and auth names typed as their classes
# rather than ``... | None`` (the runtime falls back to ``None`` if the import fails).
# tests/unit/test_stub_public_names.py keeps its names in step with the runtime module.

from types import ModuleType

from .auth import AuthProvider as AuthProvider
from .auth import UserContext as UserContext
from .auth import requires_any_permission as requires_any_permission
from .auth import requires_any_role as requires_any_role
from .auth import requires_auth as requires_auth
from .auth import requires_permission as requires_permission
from .auth import requires_role as requires_role
from .auth.auth0 import Auth0Config as Auth0Config
from .auth.auth0 import Auth0Provider as Auth0Provider
from .cqrs import CQRSExecutor as CQRSExecutor
from .cqrs import CQRSRepository as CQRSRepository
from .decorators import connection as connection
from .decorators import field as field
from .decorators import query as query
from .fastapi import FraiseQLConfig as FraiseQLConfig
from .fastapi import create_fraiseql_app as create_fraiseql_app
from .fields import fraise_field as fraise_field
from .gql.schema_builder import build_fraiseql_schema as build_fraiseql_schema
from .mutations.decorators import error as error
from .mutations.decorators import result as result
from .mutations.decorators import success as success
from .mutations.error_config import ALWAYS_DATA_CONFIG as ALWAYS_DATA_CONFIG
from .mutations.error_config import DEFAULT_ERROR_CONFIG as DEFAULT_ERROR_CONFIG
from .mutations.error_config import STRICT_STATUS_CONFIG as STRICT_STATUS_CONFIG
from .mutations.error_config import MutationErrorConfig as MutationErrorConfig
from .mutations.mutation_decorator import mutation as mutation
from .mutations.validation import validate_mutation_return as validate_mutation_return
from .optimization.decorators import dataloader_field as dataloader_field
from .security.authorization import AuthorizationDecision as AuthorizationDecision
from .security.authorization import Authorizer as Authorizer
from .security.authorization import normalize_decision as normalize_decision
from .security.decision_cache import AuthorizationCacheConfig as AuthorizationCacheConfig
from .security.decision_cache import DecisionCache as DecisionCache
from .subscriptions import subscription as subscription
from .types import fraise_input as fraise_input
from .types import fraise_type as fraise_type
from .types.common import MutationResultBase as MutationResultBase
from .types.definitions import UNSET as UNSET
from .types.enum import fraise_enum as fraise_enum
from .types.errors import Error as Error
from .types.generic import Connection as Connection
from .types.generic import Edge as Edge
from .types.generic import PageInfo as PageInfo
from .types.generic import PaginatedResponse as PaginatedResponse
from .types.generic import create_connection as create_connection
from .types.interface import fraise_interface as fraise_interface
from .types.scalars.date import DateField as Date
from .types.scalars.email_address import EmailAddressField as EmailAddress
from .types.scalars.json import JSONField as JSON  # noqa: N814
from .types.scalars.ltree import LTreeField as LTree

enum = fraise_enum
interface = fraise_interface

# Served by the module __getattr__ (not in __all__: they shadow builtins)
type = fraise_type  # noqa: A001
input = fraise_input  # noqa: A001

# The Rust extension, loaded on first access; None when it isn't built
fraiseql_rs: ModuleType | None

__version__: str

__all__ = [
    "ALWAYS_DATA_CONFIG",
    "DEFAULT_ERROR_CONFIG",
    "JSON",
    "STRICT_STATUS_CONFIG",
    "UNSET",
    "Auth0Config",
    "Auth0Provider",
    "AuthProvider",
    "AuthorizationCacheConfig",
    "AuthorizationDecision",
    "Authorizer",
    "CQRSExecutor",
    "CQRSRepository",
    "Connection",
    "Date",
    "DecisionCache",
    "Edge",
    "EmailAddress",
    "Error",
    "FraiseQLConfig",
    "LTree",
    "MutationErrorConfig",
    "MutationResultBase",
    "PageInfo",
    "PaginatedResponse",
    "UserContext",
    "build_fraiseql_schema",
    "connection",
    "create_connection",
    "create_fraiseql_app",
    "dataloader_field",
    "enum",
    "error",
    "field",
    "fraise_enum",
    "fraise_field",
    "fraise_input",
    "fraise_interface",
    "fraise_type",
    "fraiseql_rs",
    "interface",
    "mutation",
    "normalize_decision",
    "query",
    "requires_any_permission",
    "requires_any_role",
    "requires_auth",
    "requires_permission",
    "requires_role",
    "result",
    "subscription",
    "success",
    "validate_mutation_return",
]

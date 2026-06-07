"""Field-level authorization for GraphQL fields."""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import warnings
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, Union

from graphql import GraphQLError, GraphQLResolveInfo, TypeInfo, Visitor, parse, visit
from graphql.execution.values import get_argument_values
from graphql.utilities.type_info import TypeInfoVisitor

from fraiseql.core.resolver_invocation import invoke_resolver
from fraiseql.security.authorization import AuthorizationDecision, normalize_decision

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from graphql import DocumentNode, GraphQLSchema


logger = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_FIELD_CODE = "FIELD_AUTHORIZATION_ERROR"


class FieldAuthorizationError(GraphQLError):
    """Raised when field authorization fails."""

    def __init__(
        self,
        message: str = "Not authorized to access this field",
        *,
        code: str = _DEFAULT_FIELD_CODE,
    ) -> None:
        super().__init__(message, extensions={"code": code})


class PermissionCheck(Protocol):
    """Protocol for permission check functions.

    A check may return a plain ``bool`` (legacy) or an
    :class:`~fraiseql.security.AuthorizationDecision` (issue #362), sync or async.
    """

    def __call__(
        self,
        info: GraphQLResolveInfo,
        *args: Any,
        **kwargs: Any,
    ) -> Union[bool, AuthorizationDecision, Awaitable[Union[bool, AuthorizationDecision]]]:
        """Check if the field access is authorized."""
        ...


def _enforce_field_decision(
    authorized: bool | AuthorizationDecision,
    *,
    error_message: str | None,
    info: GraphQLResolveInfo,
) -> None:
    """Raise :class:`FieldAuthorizationError` if the check denied access (issue #362).

    Accepts both the legacy ``bool`` and an ``AuthorizationDecision``. A decision's
    ``code``/``message`` are surfaced on the error; a plain ``bool`` keeps the original
    ``FIELD_AUTHORIZATION_ERROR`` code so existing checks are unchanged. ``filters`` have
    no meaning at field granularity and are ignored with a warning.
    """
    decision = normalize_decision(authorized)
    if decision.filters:
        warnings.warn(
            "authorization filters are ignored at field granularity",
            RuntimeWarning,
            stacklevel=3,
        )
    if decision.allowed:
        return

    field_name = getattr(info, "field_name", "field")
    default_message = error_message or f"Not authorized to access field '{field_name}'"
    if isinstance(authorized, AuthorizationDecision):
        raise FieldAuthorizationError(
            authorized.message or default_message,
            code=authorized.code or _DEFAULT_FIELD_CODE,
        )
    raise FieldAuthorizationError(default_message)


def _copy_resolver_metadata(wrapper: Any, func: Any) -> None:
    """Copy resolver metadata onto an auth wrapper **without** setting ``__wrapped__``.

    Mirrors ``@field``'s manual metadata copy (``decorators.py``) instead of using
    ``functools.wraps``. ``functools.wraps`` sets ``wrapper.__wrapped__ = func``, and
    ``inspect.signature`` follows ``__wrapped__`` by default — so an outer ``@field`` would
    read the *inner* method's signature (e.g. ``(self)``) rather than the wrapper's real
    ``(root, info, *args, **kwargs)`` interface, then call the wrapper with too few arguments.
    That signature leak is the root of the decorator-order composition bug. Copying metadata
    by hand keeps the wrapper signature-faithful.
    """
    wrapper.__name__ = getattr(func, "__name__", wrapper.__name__)
    wrapper.__doc__ = func.__doc__
    if hasattr(func, "__annotations__"):
        wrapper.__annotations__ = func.__annotations__.copy()
    if hasattr(func, "__fraiseql_field__"):
        wrapper.__fraiseql_field__ = func.__fraiseql_field__
        wrapper.__fraiseql_field_resolver__ = func.__fraiseql_field_resolver__
        wrapper.__fraiseql_field_description__ = getattr(
            func,
            "__fraiseql_field_description__",
            None,
        )
    if hasattr(func, "__fraiseql_original_func__"):
        wrapper.__fraiseql_original_func__ = func.__fraiseql_original_func__


def authorize_field(
    permission_check: PermissionCheck,
    *,
    error_message: str | None = None,
) -> Callable[[T], T]:
    """Decorator to add field-level authorization to GraphQL fields.

    This decorator wraps field resolvers to check permissions before
    allowing access to the field.

    Args:
        permission_check: A callable that takes GraphQLResolveInfo and returns
            a boolean indicating if access is allowed. Can be sync or async.
        error_message: Optional custom error message for authorization failures.

    Returns:
        A decorator that wraps the field resolver with authorization logic.

    Example:
        ```python
        @fraise_type
        class User:
            name: str

            @field
            @authorize_field(lambda info: info.context.get("is_admin", False))
            def email(self) -> str:
                return self._email

            @field
            @authorize_field(
                lambda info: info.context.get("user_id") == self.id,
                error_message="You can only view your own phone number"
            )
            def phone(self) -> str:
                return self._phone
        ```
    """

    def decorator(func: T) -> T:
        """Wrap the field resolver with authorization logic."""
        # Get the actual function to check if it's async
        actual_func = func
        if hasattr(func, "__fraiseql_original_func__"):
            actual_func = func.__fraiseql_original_func__

        is_async_resolver = asyncio.iscoroutinefunction(actual_func)
        is_async_check = asyncio.iscoroutinefunction(permission_check)

        # Inspect permission check signature to see if it expects root
        perm_sig = inspect.signature(permission_check)
        perm_params = list(perm_sig.parameters.keys())
        # Skip 'self' if it's a method
        if perm_params and perm_params[0] == "self":
            perm_params = perm_params[1:]
        expects_root = len(perm_params) >= 2

        # Present an async wrapper whenever the resolver OR the check is async, so graphql-core
        # awaits the whole thing. An async check no longer has to be driven from a sync
        # resolver (which warned and could deadlock under a running loop); an async wrapper
        # around a sync inner resolver simply returns the plain value.
        if is_async_resolver or is_async_check:

            async def async_auth_wrapper(
                root: Any, info: GraphQLResolveInfo, *args: Any, **kwargs: Any
            ) -> Any:
                # Check permission first (await the check if it is async).
                if is_async_check:
                    if expects_root:
                        authorized = await permission_check(info, root, *args, **kwargs)
                    else:
                        authorized = await permission_check(info, *args, **kwargs)
                elif expects_root:
                    authorized = permission_check(info, root, *args, **kwargs)
                else:
                    authorized = permission_check(info, *args, **kwargs)

                _enforce_field_decision(authorized, error_message=error_message, info=info)

                # Call the wrapped resolver via the shared convention so the call adapts to
                # whatever func is (a @field wrapper in order A, a raw method in order B). The
                # wrapper may be async only because the *check* is async, so the inner resolver
                # can still be sync — await only if it actually returned an awaitable.
                result = invoke_resolver(func, root, info, *args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
                return result

            _copy_resolver_metadata(async_auth_wrapper, func)
            return async_auth_wrapper  # type: ignore[return-value]

        # Reached only when both the resolver and the check are sync.
        def sync_auth_wrapper(
            root: Any, info: GraphQLResolveInfo, *args: Any, **kwargs: Any
        ) -> Any:
            # Check permission first (always sync here).
            if expects_root:
                authorized = permission_check(info, root, *args, **kwargs)
            else:
                authorized = permission_check(info, *args, **kwargs)

            _enforce_field_decision(authorized, error_message=error_message, info=info)

            # Call the wrapped resolver via the shared convention so the call adapts to
            # whatever func is (a @field wrapper in order A, a raw method in order B).
            return invoke_resolver(func, root, info, *args, **kwargs)

        _copy_resolver_metadata(sync_auth_wrapper, func)
        return sync_auth_wrapper  # type: ignore[return-value]

    return decorator


def combine_permissions(*checks: PermissionCheck) -> PermissionCheck:
    """Combine multiple permission checks with AND logic.

    All permission checks must pass for access to be granted.

    Args:
        *checks: Variable number of permission check functions.

    Returns:
        A combined permission check function.

    Example:
        ```python
        is_authenticated = lambda info: info.context.get("user") is not None
        is_admin = lambda info: info.context.get("is_admin", False)

        @field
        @authorize_field(combine_permissions(is_authenticated, is_admin))
        def sensitive_data(self) -> str:
            return "secret"
        ```
    """

    async def async_combined_check(info: GraphQLResolveInfo, *args: Any, **kwargs: Any) -> bool:
        for check in checks:
            if asyncio.iscoroutinefunction(check):
                result = await check(info, *args, **kwargs)
            else:
                result = check(info, *args, **kwargs)

            if not result:
                return False
        return True

    def sync_combined_check(info: GraphQLResolveInfo, *args: Any, **kwargs: Any) -> bool:
        for check in checks:
            if asyncio.iscoroutinefunction(check):
                # Handle async checks in sync context
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(check(info, *args, **kwargs))
                finally:
                    loop.close()
            else:
                result = check(info, *args, **kwargs)

            if not result:
                return False
        return True

    # Return async version if any check is async
    if any(asyncio.iscoroutinefunction(check) for check in checks):
        return async_combined_check
    return sync_combined_check


def any_permission(*checks: PermissionCheck) -> PermissionCheck:
    """Combine multiple permission checks with OR logic.

    At least one permission check must pass for access to be granted.

    Args:
        *checks: Variable number of permission check functions.

    Returns:
        A combined permission check function.

    Example:
        ```python
        is_admin = lambda info: info.context.get("is_admin", False)
        is_owner = lambda info: info.context.get("user_id") == self.id

        @field
        @authorize_field(any_permission(is_admin, is_owner))
        def email(self) -> str:
            return self._email
        ```
    """

    async def async_any_check(info: GraphQLResolveInfo, *args: Any, **kwargs: Any) -> bool:
        for check in checks:
            if asyncio.iscoroutinefunction(check):
                result = await check(info, *args, **kwargs)
            else:
                result = check(info, *args, **kwargs)

            if result:
                return True
        return False

    def sync_any_check(info: GraphQLResolveInfo, *args: Any, **kwargs: Any) -> bool:
        for check in checks:
            if asyncio.iscoroutinefunction(check):
                # Handle async checks in sync context
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(check(info, *args, **kwargs))
                finally:
                    loop.close()
            else:
                result = check(info, *args, **kwargs)

            if result:
                return True
        return False

    # Return async version if any check is async
    if any(asyncio.iscoroutinefunction(check) for check in checks):
        return async_any_check
    return sync_any_check


def field_authorizer_adapter(authorizer: Any, *, field: str) -> PermissionCheck:
    """Adapt an operation-style ``Authorizer`` into a field :class:`PermissionCheck`.

    Lets one policy object serve both operation-level and field-level authorization
    (issue #362): the returned check calls ``authorizer.authorize_operation`` with
    ``operation_type="field"`` and returns its decision, which ``authorize_field``
    enforces. ``filters`` are ignored at field granularity.

    Fail-closed (issue #366): a ``GraphQLError`` raised by the authorizer propagates
    unchanged, but any other exception is normalized to a deny (never falls through to
    allow), mirroring ``enforce_operation_value`` on the operation path.
    """

    async def _check(
        info: GraphQLResolveInfo, *args: Any, **kwargs: Any
    ) -> AuthorizationDecision | bool:
        context = getattr(info, "context", None) or {}
        try:
            return await authorizer.authorize_operation(
                context=context,
                operation_type="field",
                operation_name=field,
                arguments=kwargs,
            )
        except GraphQLError:
            raise
        except Exception as exc:  # FAIL CLOSED: any error denies, never allows.
            logger.warning("field authorizer raised; denying field access", exc_info=exc)
            return AuthorizationDecision.deny(code=_DEFAULT_FIELD_CODE)

    return _check


async def _authorize_field_value(
    *, context: dict[str, Any], field: str, arguments: dict[str, Any]
) -> bool | AuthorizationDecision:
    """Evaluate the registry's default authorizer for one field, given only its context.

    The root-independent core shared by the resolver gate (:func:`_auto_field_authorization`)
    and the resolver-bypass enforcement (:func:`enforce_selected_field_authorization`), so a
    field's decision is identical whether it is reached through ``GraphQLField.resolve`` or
    served by a bypass path (issue #366). ``authorize_fields`` checks never consult the parent
    object — only ``context``, ``operation_type="field"``, the field id, and arguments — which
    is exactly what makes faithful bypass-path enforcement possible.

    Reads ``SchemaRegistry.default_authorizer`` **live** so default apps (no authorizer) are
    byte-for-byte unaffected — ``None`` returns an allow. Otherwise runs the authorizer through
    the fail-closed :func:`field_authorizer_adapter`, consulting the optional decision cache
    (issue #367). A bare ``False`` deny is given the field error code so denials shape
    consistently with or without a cache hit.
    """
    from fraiseql.gql.builders import SchemaRegistry

    registry = SchemaRegistry.get_instance()
    authorizer = registry.default_authorizer
    if authorizer is None:
        return True

    cache = registry.decision_cache
    key = cache.make_key(context, "field", field, arguments) if cache is not None else None
    if cache is not None and key is not None:
        cached = cache.get(key)
        if cached is not None:
            return cached

    # The adapter only reads ``info.context``; a context-carrying shim lets the resolver and
    # bypass paths share one evaluation without a real ``GraphQLResolveInfo``.
    raw = await field_authorizer_adapter(authorizer, field=field)(
        SimpleNamespace(context=context), **arguments
    )
    if isinstance(raw, AuthorizationDecision):
        decision = raw
    else:
        decision = (
            AuthorizationDecision.allow()
            if raw
            else AuthorizationDecision.deny(code=_DEFAULT_FIELD_CODE)
        )
    if cache is not None and key is not None:
        cache.put(key, decision)
    return decision


async def _auto_field_authorization(
    info: GraphQLResolveInfo, *, field: str, arguments: dict[str, Any]
) -> bool | AuthorizationDecision:
    """Evaluate the registry's default authorizer for one field on the resolver path (#366).

    Thin wrapper over :func:`_authorize_field_value` that sources the context from ``info``.
    """
    context = getattr(info, "context", None) or {}
    return await _authorize_field_value(context=context, field=field, arguments=arguments)


def gate_field_resolver(resolver: Callable[..., Any], *, field: str) -> Callable[..., Any]:
    """Compose automatic field-level authorization around a built field resolver (issue #366).

    Always async so a sync inner resolver composes cleanly with an async authorizer under
    graphql-core. The gate runs *before* the resolver, so a denial means the field body never
    executes (no data leaks). It is fail-closed and reuses :func:`_enforce_field_decision` for
    ``code``/``message`` shaping and the filters-ignored warning. Wrapping an already
    ``@authorize_field``-decorated resolver AND-composes the two checks (both must allow).
    """

    @functools.wraps(resolver)
    async def _gated(root: Any, info: GraphQLResolveInfo, **kwargs: Any) -> Any:
        decision = await _auto_field_authorization(info, field=field, arguments=kwargs)
        _enforce_field_decision(decision, error_message=None, info=info)
        result = resolver(root, info, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    # Mark the wrapper so the resolver-bypass dispatch (Rust merge / passthrough / turbo /
    # POST /graphql/rust) can detect — by inspecting ``GraphQLField.resolve`` — that this field
    # carries auto field-level authorization and enforce it before serving data (issue #366).
    # Without this, those paths never invoke the resolver and the gate silently fails open.
    _gated.__fraiseql_field_gated__ = True
    _gated.__fraiseql_field_auth_id__ = field

    return _gated


def iter_gated_selections(
    schema: GraphQLSchema,
    document: DocumentNode,
    variable_values: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Return ``[(field_auth_id, arguments), ...]`` for every gated field the document selects.

    A field is *gated* when its ``GraphQLField.resolve`` carries the ``__fraiseql_field_gated__``
    marker set by :func:`gate_field_resolver` (i.e. it is listed in ``authorize_fields``). The
    document is walked with graphql-core's :class:`TypeInfo` so each field is resolved against
    its real parent type — covering nested fields, named fragments, and inline fragments — and
    each field's arguments are coerced exactly as its resolver would receive them via
    ``get_argument_values``. ``field_auth_id`` is the ``"TypeName.fieldName"`` id the resolver
    path uses, so the authorizer call and decision-cache key match across paths.

    Detection is per-document (every gated field anywhere in the document is reported). For the
    common single-operation request this is exact; for a multi-operation document it can only
    *over*-report, which the fail-closed enforcement turns into a conservative deny — never a
    silent allow.
    """
    type_info = TypeInfo(schema)
    found: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()

    class _Collector(Visitor):
        def enter_field(self, node: Any, *_args: Any) -> None:
            field_def = type_info.get_field_def()
            resolve = getattr(field_def, "resolve", None)
            if not getattr(resolve, "__fraiseql_field_gated__", False):
                return
            auth_id = getattr(resolve, "__fraiseql_field_auth_id__", None)
            if auth_id is None:
                return
            try:
                arguments = get_argument_values(field_def, node, variable_values)
            except Exception:  # an invalid document is rejected by normal execution anyway
                arguments = {}
            try:
                dedup = f"{auth_id}\x00{json.dumps(arguments, sort_keys=True, default=str)}"
            except Exception:
                dedup = f"{auth_id}\x00{len(found)}"
            if dedup in seen:
                return
            seen.add(dedup)
            found.append((auth_id, arguments))

    visit(document, TypeInfoVisitor(type_info, _Collector()))
    return found


async def enforce_selected_field_authorization(
    *,
    schema: GraphQLSchema,
    query: str,
    context: dict[str, Any],
    variables: dict[str, Any] | None = None,
) -> None:
    """Enforce automatic field-level authorization (#366) on a resolver-bypass path.

    The Rust merge / passthrough / TurboRouter / ``POST /graphql/rust`` paths never invoke
    ``GraphQLField.resolve``, so the per-field gate installed by :func:`gate_field_resolver`
    would silently fail open. This re-applies it: for every gated field the document selects,
    the registry's default authorizer is consulted with ``operation_type="field"`` — through the
    same fail-closed, decision-cache-aware core the resolver path uses
    (:func:`_authorize_field_value`) — *before* any data is served. Raises a ``GraphQLError`` on
    the first deny.

    It is a no-op (returns without touching the document) when no authorizer is configured, so
    default apps pay nothing; and a no-op when the query selects no gated field or cannot be
    parsed (normal execution rejects an unparseable document).
    """
    from fraiseql.gql.builders import SchemaRegistry

    if SchemaRegistry.get_instance().default_authorizer is None:
        return
    try:
        document = parse(query)
    except Exception:
        return
    for field_id, arguments in iter_gated_selections(schema, document, variables or {}):
        decision = await _authorize_field_value(
            context=context, field=field_id, arguments=arguments
        )
        _enforce_field_decision(
            decision, error_message=None, info=SimpleNamespace(field_name=field_id)
        )

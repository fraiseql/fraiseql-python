"""Deprecated placeholder GraphQL queries for enterprise audit logging.

``AuditQueries`` never served data: its fields are not added to the ``Query`` type,
``audit_events`` returned an empty connection and ``verify_audit_chain`` returned
``True``. It will be removed. Query the ``audit_events`` table and the
``verify_audit_chain()`` SQL function from your own ``@fraiseql.query`` resolvers,
with the authorization your application needs (see
``docs/enterprise/audit-logging.md``).
"""

import warnings
from typing import Optional

from fraiseql.enterprise.audit.types import AuditEventConnection, AuditEventFilter
from fraiseql.strawberry_compat import strawberry

warnings.warn(
    "fraiseql.enterprise.audit.queries.AuditQueries is deprecated and will be removed: "
    "it is a placeholder that serves no data. Query the audit_events table and the "
    "verify_audit_chain() SQL function from your own @fraiseql.query resolvers.",
    DeprecationWarning,
    stacklevel=2,
)


@strawberry.type
class AuditQueries:
    """Deprecated placeholder: its fields return fixed values and are not exposed."""

    @strawberry.field
    def audit_events(
        self,
        filter: Optional[AuditEventFilter] = None,
        first: Optional[int] = None,
        after: Optional[str] = None,
    ) -> AuditEventConnection:
        """Return an empty connection (placeholder)."""
        return AuditEventConnection(events=[], total_count=0, chain_valid=True, has_more=False)

    @strawberry.field
    def verify_audit_chain(
        self,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> bool:
        """Return True without checking anything (placeholder)."""
        return True

"""The placeholder audit GraphQL API: AuditQueries is deprecated, LogAuditEvent is gone."""

import importlib
import sys

import pytest


def test_importing_audit_queries_warns_that_it_is_deprecated() -> None:
    sys.modules.pop("fraiseql.enterprise.audit.queries", None)

    with pytest.warns(DeprecationWarning, match="AuditQueries is deprecated"):
        importlib.import_module("fraiseql.enterprise.audit.queries")


def test_the_log_audit_event_mutation_module_is_gone() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("fraiseql.enterprise.audit.mutations")

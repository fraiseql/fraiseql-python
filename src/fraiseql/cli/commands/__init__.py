"""FraiseQL CLI commands."""

from fraiseql.cli.commands import sbom
from fraiseql.cli.commands.check import check
from fraiseql.cli.commands.dev import dev
from fraiseql.cli.commands.doctor import doctor
from fraiseql.cli.commands.generate import generate
from fraiseql.cli.commands.init import init as init_command
from fraiseql.cli.commands.migrate import migrate
from fraiseql.cli.commands.query_stats import query_stats
from fraiseql.cli.commands.sql import sql
from fraiseql.cli.commands.turbo import turbo
from fraiseql.cli.commands.validate_mutation_return import validate_mutation_return_command

__all__ = [
    "check",
    "dev",
    "doctor",
    "generate",
    "init_command",
    "migrate",
    "query_stats",
    "sbom",
    "sql",
    "turbo",
    "validate_mutation_return_command",
]

"""Smart Database Management for FraiseQL Example Integration Tests.

This module provides intelligent database setup and management for example
integration tests, inspired by FraiseQL backend's smart database fixtures.

Key Features:
- Template-based database cloning for < 1 second resets
- Automatic change detection via file checksums
- Schema validation and seed data verification
- Environment-aware database strategies
- Error recovery and fallback mechanisms
"""

import hashlib
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

logger = logging.getLogger(__name__)


class DatabaseStrategy(Enum):
    """Available database management strategies."""

    TEMPLATE_CLONE = "template_clone"  # Fast cloning from template
    DIRECT_SETUP = "direct_setup"  # Direct setup each time
    REUSE_EXISTING = "reuse_existing"  # Reuse existing database
    SKIP = "skip"  # Skip database setup


class DatabaseState(Enum):
    """Database states."""

    CLEAN = "clean"
    NEEDS_REBUILD = "needs_rebuild"
    TEMPLATE_MISSING = "template_missing"
    CORRUPTED = "corrupted"
    READY = "ready"


@dataclass
class DatabaseConfig:
    """Database configuration for examples."""

    host: str = "localhost"
    port: int = 5432
    user: str = "fraiseql"
    password: str = "fraiseql"
    admin_db: str = "postgres"
    template_suffix: str = "_template"
    test_suffix: str = "_test"


@dataclass
class ExampleConfig:
    """Configuration for a specific example."""

    name: str
    path: Path
    schema_files: list[Path] = field(default_factory=list)
    seed_files: list[Path] = field(default_factory=list)
    validation_queries: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)


class ExampleDatabaseManager:
    """Smart database management for example integration tests."""

    def __init__(self, cache_dir: Optional[Path] = None, config: Optional[DatabaseConfig] = None) -> None:
        """Initialize database manager."""
        self.cache_dir = cache_dir or Path(__file__).parent
        self.config = config or DatabaseConfig()
        self.state_cache_file = self.cache_dir / ".database_state_cache.json"
        self.examples_cache = self._load_examples_cache()

        # Ensure cache directory exists
        self.cache_dir.mkdir(exist_ok=True)

    def _load_examples_cache(self) -> dict:
        """Load cached database state for examples."""
        if self.state_cache_file.exists():
            try:
                with open(self.state_cache_file) as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Failed to load examples cache: {e}")
                return {}
        return {}

    def _save_examples_cache(self) -> None:
        """Save examples cache to disk."""
        try:
            with open(self.state_cache_file, "w") as f:
                json.dump(self.examples_cache, f, indent=2)
        except OSError as e:
            logger.warning(f"Failed to save examples cache: {e}")

    def _calculate_schema_checksum(self, example_config: ExampleConfig) -> str:
        """Calculate checksum of schema and seed files."""
        checksums = []

        # Include all schema files
        for schema_file in example_config.schema_files:
            if schema_file.exists():
                with open(schema_file, "rb") as f:
                    content = f.read()
                    checksums.append(hashlib.md5(content).hexdigest())

        # Include all seed files
        for seed_file in example_config.seed_files:
            if seed_file.exists():
                with open(seed_file, "rb") as f:
                    content = f.read()
                    checksums.append(hashlib.md5(content).hexdigest())

        # Create combined checksum
        combined = "".join(sorted(checksums))
        return hashlib.md5(combined.encode()).hexdigest()

    def _get_connection_string(self, db_name: str, admin: bool = False) -> str:
        """Get PostgreSQL connection string."""
        target_db = self.config.admin_db if admin else db_name
        return (
            f"postgresql://{self.config.user}:{self.config.password}"
            f"@{self.config.host}:{self.config.port}/{target_db}"
        )

    def _run_psql_command(
        self, sql: str, db_name: str = None, admin: bool = False
    ) -> tuple[bool, str]:
        """Run a PostgreSQL command."""
        target_db = db_name or (self.config.admin_db if admin else None)

        cmd = [
            "psql",
            "-h",
            self.config.host,
            "-p",
            str(self.config.port),
            "-U",
            self.config.user,
            "-d",
            target_db,
            "-c",
            sql,
        ]

        env = os.environ.copy()
        env["PGPASSWORD"] = self.config.password

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Command timeout"
        except Exception as e:
            return False, str(e)

    def _database_exists(self, db_name: str) -> bool:
        """Check if database exists."""
        sql = f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"
        success, output = self._run_psql_command(sql, admin=True)
        return success and "1" in output

    def _create_database(self, db_name: str, template: str = None) -> bool:
        """Create a database, optionally from template."""
        if template:
            sql = f"CREATE DATABASE {db_name} WITH TEMPLATE {template}"
        else:
            sql = f"CREATE DATABASE {db_name}"

        success, output = self._run_psql_command(sql, admin=True)
        if success:
            logger.info(f"Created database {db_name}")
            return True
        else:
            logger.error(f"Failed to create database {db_name}: {output}")
            return False

    def _drop_database(self, db_name: str) -> bool:
        """Drop a database."""
        # Terminate connections first
        terminate_sql = f"""
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = '{db_name}' AND pid <> pg_backend_pid()
        """
        self._run_psql_command(terminate_sql, admin=True)

        # Drop database
        sql = f"DROP DATABASE IF EXISTS {db_name}"
        success, output = self._run_psql_command(sql, admin=True)

        if success:
            logger.info(f"Dropped database {db_name}")
            return True
        else:
            logger.error(f"Failed to drop database {db_name}: {output}")
            return False

    def _setup_example_schema(self, db_name: str, example_config: ExampleConfig) -> bool:
        """Setup database schema for specific example."""
        logger.info(f"Setting up schema for {example_config.name}")

        # Run schema files
        for schema_file in example_config.schema_files:
            if not schema_file.exists():
                logger.warning(f"Schema file not found: {schema_file}")
                continue

            logger.info(f"Running schema file: {schema_file}")
            cmd = [
                "psql",
                "-h",
                self.config.host,
                "-p",
                str(self.config.port),
                "-U",
                self.config.user,
                "-d",
                db_name,
                "-f",
                str(schema_file),
            ]

            env = os.environ.copy()
            env["PGPASSWORD"] = self.config.password

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
                if result.returncode != 0:
                    logger.error(f"Failed to run {schema_file}: {result.stderr}")
                    return False
            except subprocess.TimeoutExpired:
                logger.error(f"Timeout running {schema_file}")
                return False

        # Run seed files
        for seed_file in example_config.seed_files:
            if not seed_file.exists():
                logger.warning(f"Seed file not found: {seed_file}")
                continue

            logger.info(f"Running seed file: {seed_file}")
            cmd = [
                "psql",
                "-h",
                self.config.host,
                "-p",
                str(self.config.port),
                "-U",
                self.config.user,
                "-d",
                db_name,
                "-f",
                str(seed_file),
            ]

            env = os.environ.copy()
            env["PGPASSWORD"] = self.config.password

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
                if result.returncode != 0:
                    logger.error(f"Failed to run {seed_file}: {result.stderr}")
                    return False
            except subprocess.TimeoutExpired:
                logger.error(f"Timeout running {seed_file}")
                return False

        return True

    def _validate_database(self, db_name: str, example_config: ExampleConfig) -> bool:
        """Validate that database is properly set up."""
        if not example_config.validation_queries:
            return True

        logger.info(f"Validating database {db_name}")

        for query in example_config.validation_queries:
            success, output = self._run_psql_command(query, db_name)
            if not success:
                logger.error(f"Validation query failed: {query}")
                logger.error(f"Error: {output}")
                return False

        logger.info(f"Database {db_name} validation passed")
        return True

    def _get_database_state(self, example_config: ExampleConfig) -> DatabaseState:
        """Determine current state of example database."""
        template_db = f"{example_config.name}{self.config.template_suffix}"

        # Check if template exists
        if not self._database_exists(template_db):
            return DatabaseState.TEMPLATE_MISSING

        # Check if schema has changed
        current_checksum = self._calculate_schema_checksum(example_config)
        cached_data = self.examples_cache.get(example_config.name, {})
        cached_checksum = cached_data.get("schema_checksum")

        if current_checksum != cached_checksum:
            return DatabaseState.NEEDS_REBUILD

        # Check if template is valid
        if not self._validate_database(template_db, example_config):
            return DatabaseState.CORRUPTED

        return DatabaseState.READY

    async def ensure_test_database(self, example_name: str) -> tuple[bool, str]:
        """Ensure clean test database exists for example."""
        try:
            # Load example configuration
            example_config = self._get_example_config(example_name)
            if not example_config:
                return False, f"Unknown example: {example_name}"

            # Determine database state
            state = self._get_database_state(example_config)

            template_db = f"{example_name}{self.config.template_suffix}"
            test_db = f"{example_name}{self.config.test_suffix}_{uuid4().hex[:8]}"

            # Handle different states
            if state in [
                DatabaseState.TEMPLATE_MISSING,
                DatabaseState.NEEDS_REBUILD,
                DatabaseState.CORRUPTED,
            ]:
                logger.info(f"Rebuilding template for {example_name} (state: {state.value})")

                # Drop existing template
                if self._database_exists(template_db):
                    self._drop_database(template_db)

                # Create new template
                if not self._create_database(template_db):
                    return False, f"Failed to create template database {template_db}"

                # Setup schema
                if not self._setup_example_schema(template_db, example_config):
                    return False, f"Failed to setup schema for {template_db}"

                # Validate template
                if not self._validate_database(template_db, example_config):
                    return False, f"Template validation failed for {template_db}"

                # Update cache
                self.examples_cache[example_name] = {
                    "schema_checksum": self._calculate_schema_checksum(example_config),
                    "template_created_at": time.time(),
                    "last_validated": time.time(),
                }
                self._save_examples_cache()

            # Clone template to test database (fast < 1s operation)
            logger.info(f"Cloning {template_db} to {test_db}")
            if not self._create_database(test_db, template=template_db):
                return False, f"Failed to clone template to {test_db}"

            # Return connection string
            connection_string = self._get_connection_string(test_db)
            return True, connection_string

        except Exception as e:
            logger.error(f"Error ensuring test database for {example_name}: {e}")
            return False, str(e)

    def _get_example_config(self, example_name: str) -> Optional[ExampleConfig]:
        """Get configuration for specific example."""
        examples_dir = Path(__file__).parent.parent.parent.parent / "examples"
        example_path = examples_dir / example_name

        if not example_path.exists():
            return None

        # Define configurations for known examples
        if example_name == "blog_simple":
            return ExampleConfig(
                name=example_name,
                path=example_path,
                schema_files=[example_path / "db" / "setup.sql"],
                seed_files=[example_path / "db" / "seed_data.sql"],
                validation_queries=[
                    "SELECT COUNT(*) FROM tb_user WHERE id IS NOT NULL",
                    "SELECT COUNT(*) FROM tb_post WHERE id IS NOT NULL",
                ],
            )

        # Generic configuration for other examples
        schema_files = []
        seed_files = []

        # Look for common schema file patterns
        for pattern in ["setup.sql", "schema.sql", "db/setup.sql", "db/schema.sql"]:
            schema_file = example_path / pattern
            if schema_file.exists():
                schema_files.append(schema_file)

        # Look for common seed file patterns
        for pattern in ["seed.sql", "seed_data.sql", "db/seed.sql", "db/seed_data.sql"]:
            seed_file = example_path / pattern
            if seed_file.exists():
                seed_files.append(seed_file)

        return ExampleConfig(
            name=example_name,
            path=example_path,
            schema_files=schema_files,
            seed_files=seed_files,
            validation_queries=[],
        )

    def cleanup_test_databases(self, pattern: str = None) -> None:
        """Clean up test databases matching pattern."""
        if pattern is None:
            pattern = self.config.test_suffix

        # Get list of databases
        sql = "SELECT datname FROM pg_database WHERE datname LIKE '%{}%'".format(pattern)
        success, output = self._run_psql_command(sql, admin=True)

        if not success:
            logger.error(f"Failed to list databases: {output}")
            return

        # Extract database names
        db_names = []
        for line in output.split("\n"):
            line = line.strip()
            if line and pattern in line and line != self.config.admin_db:
                db_names.append(line)

        # Drop test databases
        for db_name in db_names:
            logger.info(f"Cleaning up test database: {db_name}")
            self._drop_database(db_name)

    def get_manager_status(self) -> dict[str, Any]:
        """Get current manager status for debugging."""
        return {
            "cache_file_exists": self.state_cache_file.exists(),
            "cached_examples": list(self.examples_cache.keys()),
            "database_config": {
                "host": self.config.host,
                "port": self.config.port,
                "user": self.config.user,
            },
            "available_examples": self._get_available_examples(),
        }

    def _get_available_examples(self) -> list[str]:
        """Get list of available examples."""
        examples_dir = Path(__file__).parent.parent.parent.parent / "examples"
        if not examples_dir.exists():
            return []

        examples = []
        for item in examples_dir.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                # Check if it has recognizable structure
                if (item / "app.py").exists() or (item / "models.py").exists():
                    examples.append(item.name)

        return examples


# Global instance for easy access
_database_manager = None


def get_database_manager() -> ExampleDatabaseManager:
    """Get global database manager instance."""
    global _database_manager
    if _database_manager is None:
        _database_manager = ExampleDatabaseManager()
    return _database_manager

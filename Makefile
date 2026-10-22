.PHONY: help test test-unit test-integration lint format check clean db-up db-down db-logs db-reset db-status db-verify release-check release-build release-publish release

# Default target
help:
	@echo "FraiseQL v1 Development Commands"
	@echo ""
	@echo "Testing:"
	@echo "  make test               - Run all tests"
	@echo "  make test-unit          - Run unit tests only (fast, no database)"
	@echo "  make test-integration   - Run integration tests (requires Docker)"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint               - Run ruff linter"
	@echo "  make format             - Format code with ruff"
	@echo "  make check              - Run all checks (format + lint + test)"
	@echo "  make clean              - Clean build artifacts"
	@echo ""
	@echo "Database (Docker):"
	@echo "  make db-up              - Start the test PostgreSQL (localhost:5432)"
	@echo "  make db-down            - Stop test databases"
	@echo "  make db-logs            - View database logs"
	@echo "  make db-reset           - Reset test databases (remove volumes)"
	@echo "  make db-status          - Check database health"
	@echo "  make db-verify          - Check the extensions the tests use are available"
	@echo ""
	@echo "Release (PyPI):"
	@echo "  make release-check       - Pre-release checks (lint, tests, version)"
	@echo "  make release-build       - Build wheel+sdist (runs checks first)"
	@echo "  make release-publish     - Publish dist/ to PyPI"
	@echo "  make release             - Full pipeline: check -> build -> publish"
	@echo ""

# ============================================================================
# Python Development
# ============================================================================

# Run all tests (unit + integration)
test: test-unit test-integration

# Run unit tests only (no database required)
test-unit:
	@echo "Running unit tests..."
	@uv run pytest tests/unit/ -q

# Run integration tests (requires Docker databases)
test-integration: db-up
	@echo "Running integration tests..."
	@sleep 2
	@uv run pytest tests/integration/ -q

# Run ruff linter
lint:
	@uv run ruff check src/

# Format code
format:
	@uv run ruff format src/

# Run all checks
check: format lint test-unit

# Clean build artifacts
clean:
	@rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# ============================================================================
# Docker-based Test Database Management
# ============================================================================

# Start the test PostgreSQL (docker-compose.test.yml)
db-up:
	@echo "Starting the test database..."
	@docker compose -f docker-compose.test.yml up -d --wait
	@docker compose -f docker-compose.test.yml ps

# Stop test databases
db-down:
	@echo "Stopping test databases..."
	@docker compose -f docker-compose.test.yml down

# View database logs
db-logs:
	@docker compose -f docker-compose.test.yml logs -f

# Reset test databases (remove volumes)
db-reset:
	@echo "Resetting test databases (removing volumes)..."
	@docker compose -f docker-compose.test.yml down -v
	@docker compose -f docker-compose.test.yml up -d --wait
	@echo "Databases reset and started"

# Check database health status
db-status:
	@echo "Database status:"
	@docker compose -f docker-compose.test.yml ps

# Check the extensions the tests create (vector, ltree) are available
db-verify:
	@echo "Checking PostgreSQL extensions..."
	@docker compose -f docker-compose.test.yml exec -T postgres-test \
		psql -U fraiseql -d fraiseql -c "SELECT name, default_version FROM pg_available_extensions WHERE name IN ('vector', 'ltree') ORDER BY name;"

# ============================================================================
# Python Package Release (fraiseql on PyPI)
# ============================================================================

# Extract version from pyproject.toml
VERSION := $(shell grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)"/\1/')

## Pre-release checks: lint, tests, version consistency, clean working tree
release-check:
	@echo "Running pre-release checks for fraiseql v$(VERSION)..."
	@echo ""
	@echo "-- Checking clean working tree --"
	@git diff --quiet && git diff --cached --quiet || { echo "Working tree is dirty. Commit or stash changes first."; exit 1; }
	@echo "Working tree is clean"
	@echo ""
	@echo "-- Checking version consistency (pyproject.toml vs fraiseql_rs/Cargo.toml) --"
	@CARGO_VERSION=$$(grep '^version' fraiseql_rs/Cargo.toml | head -1 | sed 's/.*"\(.*\)"/\1/') && \
		if [ "$(VERSION)" != "$$CARGO_VERSION" ]; then \
			echo "Version mismatch: pyproject.toml=$(VERSION) vs fraiseql_rs/Cargo.toml=$$CARGO_VERSION"; \
			exit 1; \
		fi
	@echo "Version $(VERSION) consistent"
	@echo ""
	@echo "-- Running ruff checks --"
	@uv run ruff check src/fraiseql/ || { echo "Ruff check failed"; exit 1; }
	@uv run ruff format --check src/fraiseql/ || { echo "Ruff format check failed"; exit 1; }
	@echo "Ruff checks passed"
	@echo ""
	@echo "-- Running unit tests --"
	@uv run pytest tests/unit/ -x -q --ignore=tests/unit/security/test_kms_vault_containers.py || { echo "Unit tests failed"; exit 1; }
	@echo ""
	@echo "All pre-release checks passed for v$(VERSION)"

## Build wheel and sdist with maturin
release-build: release-check
	@echo ""
	@echo "Building fraiseql v$(VERSION)..."
	@rm -rf dist/
	@uv run maturin build --release
	@mkdir -p dist/
	@cp fraiseql_rs/target/wheels/fraiseql-$(VERSION)-*.whl dist/
	@echo ""
	@echo "Build artifacts:"
	@ls -lh dist/
	@echo ""
	@echo "-- Validating with twine --"
	@uv run twine check dist/* || { echo "Twine check failed"; exit 1; }
	@echo "Package validation passed"

## Publish to PyPI (requires TWINE_USERNAME/TWINE_PASSWORD or ~/.pypirc)
release-publish:
	@echo ""
	@echo "Publishing fraiseql v$(VERSION) to PyPI..."
	@test -d dist/ || { echo "No dist/ directory. Run 'make release-build' first."; exit 1; }
	@uv run twine upload dist/*
	@echo ""
	@echo "fraiseql v$(VERSION) published to PyPI"
	@echo "   https://pypi.org/project/fraiseql/$(VERSION)/"

## Full release pipeline: check -> build -> publish
release: release-build release-publish
	@echo ""
	@echo "Release v$(VERSION) complete!"
